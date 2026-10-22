"""Open and stop the isolated BioRenal server without a persistent CMD window."""

from __future__ import annotations

import ctypes
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
STATE = DATA / "servidor_local.json"
LOG = DATA / "servidor_local.log"
SERVER = ROOT / "app" / "backend" / "server.py"
LAN_CONFIG = DATA / "rede_local.json"


def dialog(message: str, title: str = "BioRenal ERP") -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x40)
    else:
        print(f"{title}: {message}")


def read_state() -> dict:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("port"), int) and isinstance(data.get("token"), str):
            return data
    except (FileNotFoundError, ValueError, OSError):
        pass
    return {}


def request_instance(state: dict, action: str = "status") -> bool:
    if not state:
        return False
    port = state["port"]
    if not 1 <= port <= 65535:
        return False
    scheme = state.get("scheme", "http")
    url = f"{scheme}://127.0.0.1:{port}/api/local/{action}"
    payload = b"{}" if action == "stop" else None
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"X-BioRenal-Instance": state["token"], **({"Content-Type": "application/json"} if payload else {})},
        method="POST" if payload else "GET",
    )
    try:
        handlers = [urllib.request.ProxyHandler({})]
        if scheme == "https":
            ca_path = DATA / "tls" / "ca.crt"
            handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(ca_path))))
        opener = urllib.request.build_opener(*handlers)
        with opener.open(req, timeout=1.5) as response:
            result = json.load(response)
            return response.status == 200 and (result.get("aplicacao") == "BioRenalERP" if action == "status" else result.get("sucesso") is True)
    except (OSError, ValueError, urllib.error.HTTPError):
        return False


def new_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def start(lan: bool = False) -> int:
    if not SERVER.is_file() or not (ROOT / "runtime" / "pythonw.exe").is_file():
        raise RuntimeError("Pasta do aplicativo incompleta. Mantenha runtime e app junto do iniciador.")
    current = read_state()
    if request_instance(current):
        if lan and current.get("scheme") != "https":
            raise RuntimeError("Encerre a instância local antes de iniciar o acesso pela rede.")
        webbrowser.open(f"{current.get('scheme','http')}://127.0.0.1:{current['port']}/", new=2)
        return 0
    database = DATA / "biorenal_2026.db"
    if not database.is_file():
        raise RuntimeError("Banco de dados local não encontrado.")
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("A cópia do banco não passou na verificação de integridade.")
    config = {}
    if lan:
        if not LAN_CONFIG.is_file():
            raise RuntimeError("Configuração HTTPS ausente. Siga o guia de instalação da rede local.")
        config = json.loads(LAN_CONFIG.read_text(encoding="utf-8"))
        lan_ip = str(config.get("ip", ""))
        address = ipaddress.IPv4Address(lan_ip)
        if not address.is_private or address.is_loopback or address.is_link_local:
            raise RuntimeError("Configure o IPv4 privado atual deste computador.")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as check:
            check.bind((lan_ip, 0))
        with sqlite3.connect(database) as connection:
            if connection.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0] < 1:
                raise RuntimeError("Crie primeiro o administrador pelo acesso local neste PC.")
        for name in ("ca.crt", "server.crt", "server.key"):
            if not (DATA / "tls" / name).is_file():
                raise RuntimeError(f"Certificado ausente: {name}")
    port = int(config.get("port", 8443)) if lan else new_port()
    token = secrets.token_urlsafe(32)
    scheme = "https" if lan else "http"
    state = {"pid": 0, "port": port, "token": token, "scheme": scheme}
    environment = os.environ.copy()
    environment["BIORENAL_DATA_DIR"] = str(DATA)
    environment["BIORENAL_BIND_HOST"] = "0.0.0.0" if lan else "127.0.0.1"
    if lan:
        environment["BIORENAL_LAN_IP"] = lan_ip
        environment["BIORENAL_TLS_CERT"] = str(DATA / "tls" / "server.crt")
        environment["BIORENAL_TLS_KEY"] = str(DATA / "tls" / "server.key")
    environment["BIORENAL_INSTANCE_TOKEN"] = token
    environment["PYTHONUNBUFFERED"] = "1"
    with LOG.open("ab") as output:
        process = subprocess.Popen(
            [str(ROOT / "runtime" / "pythonw.exe"), str(SERVER), str(port)],
            cwd=ROOT / "app", env=environment,
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    state["pid"] = process.pid
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError(f"Servidor terminou ao iniciar. Consulte {LOG}.")
        if request_instance(state):
            temporary = STATE.with_suffix(".tmp")
            temporary.write_text(json.dumps(state), encoding="utf-8")
            temporary.replace(STATE)
            if not webbrowser.open(f"{scheme}://127.0.0.1:{port}/", new=2):
                dialog(f"Servidor iniciado. Abra {scheme}://127.0.0.1:{port}/ no navegador.")
            return 0
        time.sleep(0.25)
    process.terminate()
    raise RuntimeError(f"Servidor não respondeu. Consulte {LOG}.")


def stop() -> int:
    state = read_state()
    if not request_instance(state):
        dialog("Nenhuma instância iniciada pelo atalho está respondendo. Se o sistema estiver aberto em outra janela, feche o CMD antigo uma única vez.")
        return 0
    if not request_instance(state, "stop"):
        raise RuntimeError("Não foi possível encerrar a instância local.")
    for _ in range(30):
        if not request_instance(state):
            break
        time.sleep(0.2)
    else:
        raise RuntimeError("O servidor ainda está respondendo. Tente encerrar novamente; o registro foi preservado.")
    if STATE.is_file() and read_state().get("token") == state["token"]:
        STATE.unlink()
    dialog("Servidor BioRenal encerrado. A aba do navegador pode ser fechada.")
    return 0


if __name__ == "__main__":
    try:
        command = sys.argv[1].lower() if len(sys.argv) > 1 else "start"
        if command == "start":
            raise SystemExit(start())
        if command == "start-lan":
            raise SystemExit(start(lan=True))
        if command == "stop":
            raise SystemExit(stop())
        raise ValueError("Comando desconhecido.")
    except Exception as exc:
        dialog(str(exc), "BioRenal ERP — erro")
        raise SystemExit(1)
