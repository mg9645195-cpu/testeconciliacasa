"""Generate a private LAN certificate for this installation; never commit data/tls."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TLS = DATA / "tls"


def openssl_command() -> str:
    found = shutil.which("openssl")
    if found:
        return found
    git_version = Path(r"C:\Program Files\Git\usr\bin\openssl.exe")
    if git_version.is_file():
        return str(git_version)
    raise RuntimeError("OpenSSL não encontrado. Instale Git for Windows antes de configurar HTTPS.")


def run(*args: str) -> None:
    subprocess.run([openssl_command(), *map(str, args)], check=True, capture_output=True)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python configurar_https_local.py 192.168.3.153")
    address = ipaddress.IPv4Address(sys.argv[1])
    if not address.is_private or address.is_loopback or address.is_link_local:
        raise ValueError("Informe o IPv4 privado deste computador na rede interna.")
    if (TLS / "server.key").exists() or (TLS / "ca.crt").exists():
        raise FileExistsError("Certificados já existem. Não substitua sem planejar a renovação nos dois computadores.")
    TLS.mkdir(parents=True, exist_ok=True)
    ca_key, ca_crt = TLS / "ca.key", TLS / "ca.crt"
    server_key, server_crt, server_csr = TLS / "server.key", TLS / "server.crt", TLS / "server.csr"
    extensions = TLS / "server.ext"
    extensions.write_text(
        f"subjectAltName=IP:{address},IP:127.0.0.1,DNS:localhost\n"
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n", encoding="ascii")
    try:
        run("req", "-x509", "-newkey", "rsa:3072", "-sha256", "-nodes", "-days", "3650",
            "-subj", "/CN=BioRenal ERP Local CA", "-keyout", ca_key, "-out", ca_crt,
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        run("req", "-new", "-newkey", "rsa:3072", "-sha256", "-nodes",
            "-subj", f"/CN={address}", "-keyout", server_key, "-out", server_csr)
        run("x509", "-req", "-in", server_csr, "-CA", ca_crt, "-CAkey", ca_key,
            "-CAcreateserial", "-out", server_crt, "-days", "365", "-sha256", "-extfile", extensions)
        run("verify", "-CAfile", ca_crt, server_crt)
    finally:
        for temporary in (ca_key, server_csr, extensions, TLS / "ca.srl"):
            temporary.unlink(missing_ok=True)
    (DATA / "rede_local.json").write_text(json.dumps({"ip": str(address), "port": 8443}, indent=2), encoding="utf-8")
    print(f"HTTPS configurado para https://{address}:8443")
    print(f"Certificado público para instalar nos PCs: {ca_crt}")
    print("A chave privada fica somente neste computador, em data/tls/server.key.")


if __name__ == "__main__":
    main()
