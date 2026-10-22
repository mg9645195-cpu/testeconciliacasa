# -*- coding: utf-8 -*-
"""
Biorenal — Servidor Full-Stack HTTP/REST + Servir Aplicação Web Estática (Port 8090).
"""

import os
import sys
import json
import base64
import urllib.parse
import threading
import secrets
import ssl
import ipaddress
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from decimal import Decimal

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from domain import (
    to_dec,
    TOLERANCE,
    TWO_PLACES,
    PLANO_DE_CONTAS,
    TIPOS_PAGAMENTO,
    TIPOS_MOVIMENTACAO,
    STATUS_CONCILIACAO_LIST,
    ORIGENS_CLASSIFICACAO,
    CANONICAL_SUPPLIER_GROUPS,
    infer_missing_supplier,
    get_canonical_supplier,
    suggest_for_movement,
    build_ferronefro_split,
    build_socio_split,
    build_notas_mistas_split,
)
from database import (
    get_conn,
    ensure_db_initialized,
    recalculate_all,
    import_from_xlsx,
    DEFAULT_XLSX_PATH,
    DATA_DIR,
)
from analytics import (
    get_dashboard_data,
    get_prestacao_contas_dre,
    get_integridade_and_fornecedores,
    export_to_official_xlsx,
)
from tributos import get_tributos, save_note, save_config, save_tax_guide, import_tax_workbook, ensure_tax_schema
from pagamentos import (ensure_payment_schema, get_programacao, save_programacao,
    import_programacao_xlsx, import_extrato_links, get_prestadores,
    save_prestador, save_banco, get_banco, import_prestadores_xlsx,
    get_candidatos_conciliacao, vincular_programacao_extrato, marcar_prestadores_enviados)
from auth import (ensure_auth_schema, is_configured, setup_admin, login, current_session,
                  logout, list_users, save_user, change_password, SESSION_SECONDS)

PUBLIC_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "public")


class BiorenalRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PUBLIC_DIR, **kwargs)

    def log_message(self, format, *args):
        # Clean concise logging
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _send_json(self, data, status=200, cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _allow_local_request(self):
        """Deny browser requests routed to this local service from other sites."""
        host = self.headers.get("Host", "").lower()
        port = self.server.server_port
        permitted = {f"127.0.0.1:{port}", f"localhost:{port}"}
        for name in (os.environ.get("BIORENAL_LAN_IP", ""), os.environ.get("BIORENAL_LAN_HOST", "")):
            if name:
                permitted.add(f"{name.lower()}:{port}")
        if host not in permitted:
            self._send_json({"erro": "Host não autorizado."}, status=403)
            return False
        origin = self.headers.get("Origin")
        scheme = "https" if getattr(self.server, "is_tls", False) else "http"
        if origin and origin.rstrip("/").lower() != f"{scheme}://{host}":
            self._send_json({"erro": "Origem não autorizada."}, status=403)
            return False
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            self._send_json({"erro": "Origem não autorizada."}, status=403)
            return False
        return True

    def _token(self):
        try:
            cookies = SimpleCookie()
            cookies.load(self.headers.get("Cookie", ""))
            return cookies["biorenal_session"].value if "biorenal_session" in cookies else ""
        except Exception:
            return ""

    def _session(self):
        return current_session(self._token())

    def _session_cookie(self, token):
        secure = "; Secure" if getattr(self.server, "is_tls", False) else ""
        if not token:
            return f"biorenal_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0{secure}"
        return f"biorenal_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}{secure}"

    def _require_session(self, path, write=False):
        session = self._session()
        if not session:
            if path.startswith("/api/"):
                self._send_json({"erro": "Faça login para continuar."}, status=401)
            else:
                self.send_response(302)
                self.send_header("Location", "/login.html")
                self.end_headers()
            return None
        role = session["usuario"]["role"]
        if write and role == "CONSULTA" and path not in ("/api/auth/logout", "/api/auth/password"):
            self._send_json({"erro": "Seu perfil não permite alterações."}, status=403)
            return None
        admin_only = {"/api/xlsx/reset", "/api/xlsx/upload", "/api/parametros",
                      "/api/tributos/config", "/api/prestadores/banco/salvar",
                      "/api/cadastros/fornecedores/salvar", "/api/cadastros/fornecedores/remover",
                      "/api/extrato/excluir", "/api/extrato/corrigir-ban00697"}
        restricted_reads = {"/api/prestadores/relatorio", "/api/prestadores/banco", "/api/xlsx/export"}
        if (write and path in admin_only or not write and path in restricted_reads) and role == "CONSULTA":
            self._send_json({"erro": "Acesso restrito ao financeiro."}, status=403)
            return None
        if write and path in admin_only and role != "ADMIN":
            self._send_json({"erro": "Apenas o administrador pode executar esta ação."}, status=403)
            return None
        return session

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length < 0 or length > 25_000_000:
            raise ValueError("Requisição acima do tamanho permitido.")
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def do_OPTIONS(self):
        self._send_json({"erro": "Preflight de outra origem não autorizado."}, status=403)

    def do_HEAD(self):
        self.send_response(405)
        self.end_headers()

    def do_GET(self):
        if not self._allow_local_request():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if path == "/api/local/status" and os.environ.get("BIORENAL_INSTANCE_TOKEN"):
                token = self.headers.get("X-BioRenal-Instance", "")
                if not secrets.compare_digest(token, os.environ["BIORENAL_INSTANCE_TOKEN"]):
                    return self._send_json({"erro": "Instância não autorizada."}, status=403)
                return self._send_json({"aplicacao": "BioRenalERP", "status": "ativo"})

            if path == "/api/auth/status":
                session = self._session()
                return self._send_json({"configured": is_configured(), "authenticated": bool(session),
                                        **(session or {})})

            if path in ("/login.html", "/css/login.css", "/js/login.js",
                        "/img/logo-biorenal.png", "/img/icon-biorenal-erp.png"):
                return super().do_GET()

            session = self._require_session(path)
            if not session:
                return

            if path == "/usuarios.html" and session["usuario"]["role"] != "ADMIN":
                return self._send_json({"erro": "Área restrita ao administrador."}, status=403)

            if path == "/api/auth/users":
                if session["usuario"]["role"] != "ADMIN":
                    return self._send_json({"erro": "Área restrita ao administrador."}, status=403)
                return self._send_json({"usuarios": list_users()})

            if path in ("/api/prestadores/relatorio", "/api/prestadores/banco", "/api/xlsx/export") and session["usuario"]["role"] == "CONSULTA":
                return self._send_json({"erro": "Acesso restrito ao financeiro."}, status=403)

            if path == "/api/bootstrap":
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("SELECT chave, valor FROM config_parametros")
                params = {r["chave"]: r["valor"] for r in cur.fetchall()}
                cur.execute("SELECT DISTINCT fornecedor_canonico FROM extrato WHERE fornecedor_canonico != '' ORDER BY fornecedor_canonico")
                fornecedores = [r["fornecedor_canonico"] for r in cur.fetchall()]
                conn.close()
                return self._send_json({
                    "plano_de_contas": PLANO_DE_CONTAS,
                    "tipos_pagamento": TIPOS_PAGAMENTO,
                    "tipos_movimentacao": TIPOS_MOVIMENTACAO,
                    "status_conciliacao": STATUS_CONCILIACAO_LIST,
                    "origens_classificacao": ORIGENS_CLASSIFICACAO,
                    "parametros": params,
                    "fornecedores_canonicos": fornecedores,
                    "grupos_canonicos": CANONICAL_SUPPLIER_GROUPS,
                })

            if path == "/api/dashboard":
                periodo = qs.get("periodo", ["ALL"])[0]
                regime = qs.get("regime", ["CAIXA"])[0]
                fornecedor = qs.get("fornecedor", [""])[0]
                categoria = qs.get("categoria", [""])[0]
                data = get_dashboard_data(periodo, regime, fornecedor, categoria)
                return self._send_json(data)

            if path == "/api/conciliacao/fila":
                return self._send_json(self._get_fila_conciliacao())

            if path == "/api/extrato":
                return self._send_json(self._get_extrato_list(qs))

            if path == "/api/prestacao-contas":
                periodo = qs.get("periodo", ["ALL"])[0]
                regime = qs.get("regime", ["CAIXA"])[0]
                return self._send_json(get_prestacao_contas_dre(periodo, regime))

            if path == "/api/tributos":
                return self._send_json(get_tributos(int(qs.get("ano", ["2026"])[0])))

            if path == "/api/programacao":
                return self._send_json(get_programacao(qs.get("inicio", [""])[0], qs.get("fim", [""])[0]))

            if path == "/api/programacao/candidatos":
                return self._send_json(get_candidatos_conciliacao(int(qs.get("id", ["0"])[0])))

            if path == "/api/prestadores":
                return self._send_json(get_prestadores(qs.get("inicio", [""])[0], qs.get("fim", [""])[0]))

            if path == "/api/prestadores/relatorio":
                return self._send_json(get_prestadores(qs.get("inicio", [""])[0], qs.get("fim", [""])[0], include_bank=True))

            if path == "/api/prestadores/banco":
                return self._send_json(get_banco(int(qs.get("id", ["0"])[0])))

            if path == "/api/integridade":
                return self._send_json(get_integridade_and_fornecedores())

            if path == "/api/cadastros/fornecedores":
                return self._send_json(self._get_cadastros_fornecedores())

            if path == "/api/cadastros/fornecedores/preview":
                return self._send_json(self._preview_supplier_alias(qs))

            if path == "/api/xlsx/export":
                xlsx_bytes = export_to_official_xlsx()
                filename = "NOVO MODELO DE CONCILIACAO BANCARIA COM RATEIO - 2026 - ATUALIZADO.xlsx"
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(len(xlsx_bytes)))
                self.end_headers()
                self.wfile.write(xlsx_bytes)
                return

            # Static files fallback
            return super().do_GET()

        except Exception as e:
            return self._send_json({"erro": str(e)}, status=500)

    def do_POST(self):
        if not self._allow_local_request():
            return
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            return self._send_json({"erro": "Envie JSON pela aplicação local."}, status=415)
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_json_body()

            if path == "/api/local/stop" and os.environ.get("BIORENAL_INSTANCE_TOKEN"):
                token = self.headers.get("X-BioRenal-Instance", "")
                if not secrets.compare_digest(token, os.environ["BIORENAL_INSTANCE_TOKEN"]):
                    return self._send_json({"erro": "Instância não autorizada."}, status=403)
                self._send_json({"sucesso": True, "mensagem": "Encerrando servidor local."})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

            if path == "/api/auth/setup":
                if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                    return self._send_json({"erro": "O administrador inicial deve ser criado neste computador."}, status=403)
                return self._send_json(setup_admin(body))

            if path == "/api/auth/login":
                result, token = login(body, self.client_address[0])
                return self._send_json(result, cookie=self._session_cookie(token))

            session = self._require_session(path, write=True)
            if not session:
                return
            if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf_token"]):
                return self._send_json({"erro": "Sessão inválida. Atualize a página e tente novamente."}, status=403)

            if path == "/api/auth/logout":
                logout(self._token())
                return self._send_json({"sucesso": True}, cookie=self._session_cookie(""))

            if path == "/api/auth/password":
                result = change_password(body, session["usuario"]["id"])
                return self._send_json(result, cookie=self._session_cookie(""))

            if path == "/api/auth/users":
                if session["usuario"]["role"] != "ADMIN":
                    return self._send_json({"erro": "Área restrita ao administrador."}, status=403)
                return self._send_json(save_user(body, session["usuario"]["id"]))

            if path == "/api/conciliacao/aprovar-sugeridos":
                return self._send_json(self._aprovar_sugeridos(body))

            if path == "/api/conciliacao/aprovar-pendentes-revisar":
                return self._send_json(self._aprovar_pendentes_revisar(body))

            if path == "/api/conciliacao/autopreencher-fornecedores":
                return self._send_json(self._autopreencher_fornecedores(body))

            if path == "/api/conciliacao/aplicar-sugestoes":
                return self._send_json(self._aplicar_sugestoes_lote(body))

            if path == "/api/extrato/salvar-rateio":
                return self._send_json(self._salvar_rateio(body))

            if path == "/api/extrato/editar-lancamento":
                return self._send_json(self._editar_lancamento(body))

            if path == "/api/extrato/desconsiderar-rateio":
                return self._send_json(self._desconsiderar_no_rateio(body))

            if path == "/api/extrato/excluir":
                return self._send_json(self._excluir_lancamento(body))

            if path == "/api/extrato/novo":
                return self._send_json(self._criar_novo_movimento(body))

            if path == "/api/extrato/corrigir-ban00697":
                return self._send_json(self._corrigir_ban00697(body))

            if path == "/api/templates/gerar":
                return self._send_json(self._gerar_template(body))

            if path == "/api/parametros":
                return self._send_json(self._salvar_parametros(body))

            if path == "/api/tributos/nota":
                return self._send_json({"sucesso": True, "nota": save_note(body)})

            if path == "/api/tributos/guia":
                return self._send_json({"sucesso": True, "guia": save_tax_guide(body)})

            if path == "/api/tributos/config":
                return self._send_json({"sucesso": True, "config": save_config(body)})

            if path == "/api/tributos/importar":
                encoded = body.get("file_base64", "")
                if not encoded or len(encoded) > 14_000_000:
                    raise ValueError("Selecione uma planilha de até 10 MB.")
                return self._send_json({"sucesso": True, **import_tax_workbook(base64.b64decode(encoded, validate=True))})

            if path == "/api/programacao/salvar":
                return self._send_json(save_programacao(body))

            if path == "/api/programacao/vincular-extrato":
                return self._send_json(vincular_programacao_extrato(body))

            if path == "/api/programacao/importar":
                encoded = body.get("file_base64", "")
                if not encoded or len(encoded) > 14_000_000:
                    raise ValueError("Selecione uma planilha de até 10 MB.")
                return self._send_json({"sucesso": True, **import_programacao_xlsx(base64.b64decode(encoded, validate=True))})

            if path == "/api/programacao/importar-links-extrato":
                encoded = body.get("file_base64", "")
                if not encoded or len(encoded) > 20_000_000:
                    raise ValueError("Selecione a conciliação de até 15 MB.")
                return self._send_json({"sucesso": True, **import_extrato_links(base64.b64decode(encoded, validate=True))})

            if path == "/api/prestadores/salvar":
                return self._send_json(save_prestador(body))

            if path == "/api/prestadores/registrar-envio":
                return self._send_json(marcar_prestadores_enviados(body))

            if path == "/api/prestadores/banco/salvar":
                return self._send_json(save_banco(body))

            if path == "/api/prestadores/importar":
                encoded = body.get("file_base64", "")
                if not encoded or len(encoded) > 14_000_000:
                    raise ValueError("Selecione uma planilha de até 10 MB.")
                return self._send_json({"sucesso": True, **import_prestadores_xlsx(base64.b64decode(encoded, validate=True))})

            if path == "/api/cadastros/fornecedores/salvar":
                return self._send_json(self._save_supplier_alias(body))

            if path == "/api/cadastros/fornecedores/remover":
                return self._send_json(self._remove_supplier_alias(body))

            if path == "/api/xlsx/reset":
                res = import_from_xlsx(DEFAULT_XLSX_PATH)
                return self._send_json({"sucesso": True, "mensagem": "Banco local restaurado a partir da planilha oficial 2026.", "detalhes": res})

            if path == "/api/xlsx/upload":
                b64 = body.get("file_base64", "")
                if not b64:
                    return self._send_json({"erro": "Arquivo não enviado."}, status=400)
                raw_bytes = base64.b64decode(b64)
                upload_path = os.path.join(DATA_DIR, "UPLOADED_CONCILIACAO_2026.xlsx")
                with open(upload_path, "wb") as f:
                    f.write(raw_bytes)
                res = import_from_xlsx(upload_path)
                return self._send_json({"sucesso": True, "mensagem": "Planilha .xlsx importada com sucesso!", "detalhes": res})

            return self._send_json({"erro": f"Rota desconhecida: {path}"}, status=404)

        except ValueError as ve:
            return self._send_json({"erro": str(ve)}, status=400)
        except Exception as e:
            return self._send_json({"erro": str(e)}, status=500)

    # ==========================================================================
    # HANDLERS INTERNOS DOS MÓDULOS
    # ==========================================================================
    def _get_cadastros_fornecedores(self):
        conn = get_conn()
        try:
            fornecedores = [r["fornecedor_canonico"] for r in conn.execute(
                "SELECT DISTINCT fornecedor_canonico FROM extrato WHERE TRIM(COALESCE(fornecedor_canonico, '')) <> '' ORDER BY fornecedor_canonico"
            )]
            nomes_origem = [r["nome"] for r in conn.execute(
                "SELECT DISTINCT fornecedor_favorecido AS nome FROM extrato WHERE TRIM(COALESCE(fornecedor_favorecido, '')) <> '' ORDER BY nome"
            )]
            aliases = [dict(r) for r in conn.execute(
                "SELECT alias, canonico, atualizado_em FROM fornecedor_aliases ORDER BY alias"
            )]
            auditoria = [dict(r) for r in conn.execute(
                "SELECT acao, alias, canonico_anterior, canonico_novo, criado_em FROM auditoria_cadastros ORDER BY id DESC LIMIT 30"
            )]
            return {"fornecedores": fornecedores, "nomes_origem": nomes_origem, "aliases": aliases, "auditoria": auditoria}
        finally:
            conn.close()

    def _preview_supplier_alias(self, qs):
        alias = (qs.get("alias", [""])[0] or "").strip()
        canonico = (qs.get("canonico", [""])[0] or "").strip()
        if not alias or not canonico or len(alias) > 120 or len(canonico) > 120:
            raise ValueError("Informe nomes de origem e destino válidos (até 120 caracteres).")
        if alias.casefold() == canonico.casefold():
            raise ValueError("O nome de origem deve ser diferente do nome de destino.")
        conn = get_conn()
        try:
            existing_target = conn.execute(
                "SELECT canonico FROM fornecedor_aliases WHERE alias = ?", (canonico,)
            ).fetchone()
            if existing_target:
                raise ValueError("O destino já é um apelido de outro cadastro. Escolha o nome canônico final.")
            rows = [dict(r) for r in conn.execute(
                """SELECT id_lanc, data, fornecedor_favorecido, fornecedor_canonico,
                          entrada, saida, aplicacao, resgate
                   FROM extrato
                   WHERE UPPER(TRIM(COALESCE(fornecedor_favorecido, ''))) = UPPER(?)
                      OR UPPER(TRIM(COALESCE(fornecedor_canonico, ''))) = UPPER(?)
                   ORDER BY ordem""", (alias, alias)
            )]
            return {
                "alias": alias, "canonico": canonico,
                "qtd_afetada": len(rows),
                "ids_amostra": [r["id_lanc"] for r in rows[:10]],
                "total_saidas": float(sum((to_dec(r["saida"]) + to_dec(r["aplicacao"]) for r in rows), Decimal("0.00"))),
                "total_entradas": float(sum((to_dec(r["entrada"]) + to_dec(r["resgate"]) for r in rows), Decimal("0.00"))),
            }
        finally:
            conn.close()

    def _save_supplier_alias(self, body):
        alias = (body.get("alias") or "").strip()
        canonico = (body.get("canonico") or "").strip()
        expected = body.get("qtd_afetada")
        preview = self._preview_supplier_alias({"alias": [alias], "canonico": [canonico]})
        if expected is None or int(expected) != preview["qtd_afetada"]:
            raise ValueError("Os lançamentos mudaram desde a prévia. Confira novamente antes de salvar.")
        if preview["qtd_afetada"] == 0:
            raise ValueError("Nenhum lançamento usa este nome. Confira a grafia antes de salvar.")
        conn = get_conn()
        try:
            previous = conn.execute("SELECT canonico FROM fornecedor_aliases WHERE alias = ?", (alias,)).fetchone()
            conn.execute(
                "INSERT INTO fornecedor_aliases(alias, canonico) VALUES (?, ?) "
                "ON CONFLICT(alias) DO UPDATE SET canonico = excluded.canonico, atualizado_em = CURRENT_TIMESTAMP",
                (alias, canonico),
            )
            conn.execute(
                "INSERT INTO auditoria_cadastros(acao, alias, canonico_anterior, canonico_novo) VALUES (?, ?, ?, ?)",
                ("SALVAR_ALIAS", alias, previous["canonico"] if previous else None, canonico),
            )
            recalculate_all(conn)
            return {"sucesso": True, "qtd_afetada": preview["qtd_afetada"]}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _remove_supplier_alias(self, body):
        alias = (body.get("alias") or "").strip()
        conn = get_conn()
        try:
            previous = conn.execute("SELECT canonico FROM fornecedor_aliases WHERE alias = ?", (alias,)).fetchone()
            if not previous:
                raise ValueError("Vínculo não encontrado.")
            conn.execute("DELETE FROM fornecedor_aliases WHERE alias = ?", (alias,))
            conn.execute(
                "INSERT INTO auditoria_cadastros(acao, alias, canonico_anterior) VALUES (?, ?, ?)",
                ("REMOVER_ALIAS", alias, previous["canonico"]),
            )
            recalculate_all(conn)
            return {"sucesso": True}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _get_fila_conciliacao(self):
        conn = get_conn()
        cur = conn.cursor()

        # 1. Aba 1: Validar Sugeridos (ORIGEM = SUGERIDO)
        cur.execute(
            """
            SELECT r.*, e.historico_banco, e.fornecedor_canonico, e.competencia_extraida, e.documento
            FROM rateios r
            JOIN extrato e ON e.id_lanc = r.id_lanc
            WHERE r.origem_classificacao = 'SUGERIDO'
            ORDER BY e.ordem ASC, r.id_rateio ASC
            """
        )
        sugeridos = [dict(r) for r in cur.fetchall()]

        # Group sugeridos by fornecedor_canonico for 1-click batch approval
        grupos_sugeridos = {}
        for s in sugeridos:
            fc = s["fornecedor_canonico"] or s["fornecedor"] or "OUTROS"
            g = grupos_sugeridos.setdefault(fc, {"fornecedor": fc, "qtd": 0, "valor_total": Decimal("0.00"), "ids_rateio": []})
            g["qtd"] += 1
            g["valor_total"] += to_dec(s["valor"])
            g["ids_rateio"].append(s["id_rateio"])

        resumo_grupos_sugeridos = [
            {
                "fornecedor": k,
                "qtd": v["qtd"],
                "valor_total": float(v["valor_total"]),
                "ids_rateio": v["ids_rateio"],
            }
            for k, v in sorted(grupos_sugeridos.items(), key=lambda x: x[1]["valor_total"], reverse=True)
        ]

        # 2. Aba 2: Classificar Pendentes (165 movimentos NÃO CLASSIFICADOS / R$ 2.117.734,75)
        cur.execute(
            """
            SELECT * FROM extrato
            WHERE status_rateio IN ('NÃO CLASSIFICADO', 'PENDENTE DE RATEIO')
            ORDER BY ordem ASC
            """
        )
        movs_nao_class = [dict(r) for r in cur.fetchall()]
        pendentes_com_sugestao = []
        total_nao_class_val = Decimal("0.00")

        for m in movs_nao_class:
            val = to_dec(m["entrada"]) + to_dec(m["saida"]) + to_dec(m["aplicacao"]) + to_dec(m["resgate"])
            total_nao_class_val += val
            sug = suggest_for_movement(m)
            pendentes_com_sugestao.append({
                "movimento": m,
                "valor_movimento": float(val),
                "sugestao": sug,
            })

        # 3. Movimentos sem Fornecedor ou sem Status de Conciliação (ex: BAN-01029 a BAN-01061, BAN-00949, BAN-00961)
        cur.execute(
            """
            SELECT * FROM extrato
            WHERE fornecedor_favorecido IS NULL OR TRIM(fornecedor_favorecido) = '' OR TRIM(fornecedor_favorecido) = '-'
               OR status_conciliacao IS NULL OR TRIM(status_conciliacao) = ''
               OR tipo_pagamento = 'PP'
            ORDER BY ordem ASC
            """
        )
        sem_forn_rows = [dict(r) for r in cur.fetchall()]
        higienizacao_forn = []
        for m in sem_forn_rows:
            forn_atual = (m["fornecedor_favorecido"] or "").strip()
            forn_inferido = forn_atual if (forn_atual and forn_atual != "-") else infer_missing_supplier(m["historico_banco"] or "")
            higienizacao_forn.append({
                "id_lanc": m["id_lanc"],
                "data": m["data"],
                "historico_banco": m["historico_banco"],
                "fornecedor_atual": forn_atual,
                "fornecedor_sugerido": forn_inferido,
                "status_conciliacao_atual": m["status_conciliacao"] or "",
                "status_conciliacao_sugerido": "Conciliado",
                "tipo_pagamento_atual": m["tipo_pagamento"] or "",
                "tipo_pagamento_sugerido": "PIX" if m["tipo_pagamento"] == "PP" else (m["tipo_pagamento"] or "PIX"),
                "valor": float(to_dec(m["entrada"]) + to_dec(m["saida"]) + to_dec(m["aplicacao"]) + to_dec(m["resgate"])),
            })

        # 4. Linhas já classificadas (com categoria OK) mas ainda marcadas PENDENTE ou REVISAR (99 linhas de Jul-Ago)
        cur.execute(
            """
            SELECT r.*, e.historico_banco, e.fornecedor_canonico, e.competencia_extraida
            FROM rateios r
            JOIN extrato e ON e.id_lanc = r.id_lanc
            WHERE r.origem_classificacao IN ('PENDENTE', 'REVISAR')
              AND r.categoria IS NOT NULL AND TRIM(r.categoria) != ''
              AND e.status_rateio != 'DESCONSIDERADO'
            ORDER BY e.ordem ASC, r.id_rateio ASC
            """
        )
        pendentes_ja_classificados = [dict(r) for r in cur.fetchall()]

        # 5. Lançamentos Desconsiderados no Rateio
        cur.execute(
            """
            SELECT * FROM extrato
            WHERE status_rateio = 'DESCONSIDERADO' OR desconsiderar_rateio = 1
            ORDER BY ordem ASC
            """
        )
        desconsiderados_rows = [dict(r) for r in cur.fetchall()]

        conn.close()
        return {
            "aba_sugeridos": {
                "total_linhas": len(sugeridos),
                "valor_total": float(sum((to_dec(s["valor"]) for s in sugeridos), Decimal("0.00"))),
                "grupos_por_fornecedor": resumo_grupos_sugeridos,
                "itens": sugeridos,
            },
            "aba_nao_classificados": {
                "total_movimentos": len(pendentes_com_sugestao),
                "valor_total": float(total_nao_class_val),
                "itens": pendentes_com_sugestao,
            },
            "aba_higienizacao_fornecedores": {
                "total_movimentos": len(higienizacao_forn),
                "itens": higienizacao_forn,
            },
            "aba_pendentes_classificados": {
                "total_linhas": len(pendentes_ja_classificados),
                "valor_total": float(sum((to_dec(p["valor"]) for p in pendentes_ja_classificados), Decimal("0.00"))),
                "itens": pendentes_ja_classificados,
            },
            "aba_desconsiderados": {
                "total_movimentos": len(desconsiderados_rows),
                "valor_total": float(
                    sum(
                        (to_dec(d["entrada"]) + to_dec(d["saida"]) + to_dec(d["aplicacao"]) + to_dec(d["resgate"]) for d in desconsiderados_rows),
                        Decimal("0.00"),
                    )
                ),
                "itens": desconsiderados_rows,
            },
        }

    def _aprovar_sugeridos(self, body):
        ids_rateio = body.get("ids_rateio", [])
        fornecedor = body.get("fornecedor", "")
        aprovar_todos = body.get("aprovar_todos", False)

        conn = get_conn()
        cur = conn.cursor()

        if aprovar_todos:
            cur.execute("UPDATE rateios SET origem_classificacao = 'CONFIRMADO' WHERE origem_classificacao = 'SUGERIDO'")
            afetados = cur.rowcount
        elif fornecedor:
            cur.execute(
                """
                UPDATE rateios
                SET origem_classificacao = 'CONFIRMADO'
                WHERE origem_classificacao = 'SUGERIDO'
                  AND id_lanc IN (SELECT id_lanc FROM extrato WHERE fornecedor_canonico = ? OR fornecedor_favorecido = ?)
                """,
                (fornecedor, fornecedor),
            )
            afetados = cur.rowcount
        elif ids_rateio:
            placeholders = ",".join("?" for _ in ids_rateio)
            cur.execute(
                f"UPDATE rateios SET origem_classificacao = 'CONFIRMADO' WHERE id_rateio IN ({placeholders})",
                ids_rateio,
            )
            afetados = cur.rowcount
        else:
            afetados = 0

        recalculate_all(conn)
        conn.close()
        return {"sucesso": True, "linhas_aprovadas": afetados}

    def _aprovar_pendentes_revisar(self, body):
        ids_rateio = body.get("ids_rateio", [])
        aprovar_todos = body.get("aprovar_todos", False)

        conn = get_conn()
        cur = conn.cursor()
        if aprovar_todos:
            cur.execute(
                """
                UPDATE rateios
                SET origem_classificacao = 'CONFIRMADO'
                WHERE origem_classificacao IN ('PENDENTE', 'REVISAR')
                  AND categoria IS NOT NULL AND TRIM(categoria) != ''
                """
            )
            afetados = cur.rowcount
        elif ids_rateio:
            placeholders = ",".join("?" for _ in ids_rateio)
            cur.execute(
                f"UPDATE rateios SET origem_classificacao = 'CONFIRMADO' WHERE id_rateio IN ({placeholders})",
                ids_rateio,
            )
            afetados = cur.rowcount
        else:
            afetados = 0

        recalculate_all(conn)
        conn.close()
        return {"sucesso": True, "linhas_aprovadas": afetados}

    def _autopreencher_fornecedores(self, body):
        ids_lanc = body.get("ids_lanc", [])
        conn = get_conn()
        cur = conn.cursor()

        if ids_lanc:
            placeholders = ",".join("?" for _ in ids_lanc)
            cur.execute(f"SELECT * FROM extrato WHERE id_lanc IN ({placeholders})", ids_lanc)
        else:
            cur.execute(
                """
                SELECT * FROM extrato
                WHERE fornecedor_favorecido IS NULL OR TRIM(fornecedor_favorecido) = '' OR TRIM(fornecedor_favorecido) = '-'
                   OR status_conciliacao IS NULL OR TRIM(status_conciliacao) = ''
                   OR tipo_pagamento = 'PP'
                """
            )
        rows = [dict(r) for r in cur.fetchall()]
        updated = 0
        for m in rows:
            forn = (m["fornecedor_favorecido"] or "").strip()
            if not forn or forn == "-":
                forn = infer_missing_supplier(m["historico_banco"] or "")
            st_conc = (m["status_conciliacao"] or "").strip() or "Conciliado"
            tp = "PIX" if m["tipo_pagamento"] == "PP" else (m["tipo_pagamento"] or "PIX")
            cur.execute(
                "UPDATE extrato SET fornecedor_favorecido = ?, status_conciliacao = ?, tipo_pagamento = ? WHERE id_lanc = ?",
                (forn, st_conc, tp, m["id_lanc"]),
            )
            updated += 1

        recalculate_all(conn)
        conn.close()
        return {"sucesso": True, "movimentos_atualizados": updated}

    def _aplicar_sugestoes_lote(self, body):
        """
        Aplica sugestões automáticas (1:1 ou 1:N) para uma lista de IDs ou todos os 165 movimentos NÃO CLASSIFICADOS.
        Também suporta custom_rateios caso o usuário tenha editado na fila antes de confirmar.
        """
        ids_lanc = body.get("ids_lanc", [])
        aplicar_todos = body.get("aplicar_todos", False)
        custom_rateios = body.get("custom_rateios", None)
        custom_fornecedor = body.get("fornecedor_favorecido", None)

        conn = get_conn()
        cur = conn.cursor()

        if aplicar_todos:
            cur.execute("SELECT * FROM extrato WHERE status_rateio IN ('NÃO CLASSIFICADO', 'PENDENTE DE RATEIO') ORDER BY ordem ASC")
        elif ids_lanc:
            placeholders = ",".join("?" for _ in ids_lanc)
            cur.execute(f"SELECT * FROM extrato WHERE id_lanc IN ({placeholders}) ORDER BY ordem ASC", ids_lanc)
        else:
            conn.close()
            return {"sucesso": False, "movimentos_classificados": 0}

        movs = [dict(r) for r in cur.fetchall()]
        count_movs = 0
        count_rateios = 0

        for m in movs:
            id_lanc = m["id_lanc"]
            sug = suggest_for_movement(m)
            forn_final = custom_fornecedor if (custom_fornecedor and len(movs) == 1) else sug["fornecedor_sugerido"]
            tp_final = sug["tipo_pagamento_corrigido"]
            rateios_list = custom_rateios if (custom_rateios and len(movs) == 1) else sug["rateios_sugeridos"]

            # Validate exact Decimal sum
            val_banco = to_dec(m["entrada"]) + to_dec(m["saida"]) + to_dec(m["aplicacao"]) + to_dec(m["resgate"])
            soma_rat = sum((to_dec(item["valor"]) for item in rateios_list), Decimal("0.00"))
            if abs(val_banco - soma_rat) > TOLERANCE:
                raise ValueError(
                    f"Fidelidade Contábil Violada em {id_lanc}: Banco R$ {val_banco} != Rateio R$ {soma_rat}"
                )

            cur.execute(
                """
                UPDATE extrato
                SET fornecedor_favorecido = ?, status_conciliacao = 'Conciliado', tipo_pagamento = ?
                WHERE id_lanc = ?
                """,
                (forn_final, tp_final, id_lanc),
            )
            cur.execute("DELETE FROM rateios WHERE id_lanc = ?", (id_lanc,))

            for item in rateios_list:
                cur.execute(
                    """
                    INSERT INTO rateios (
                        id_lanc, categoria, subcategoria, valor,
                        detalhe_componente, origem_classificacao
                    ) VALUES (?, ?, ?, ?, ?, 'CONFIRMADO')
                    """,
                    (
                        id_lanc,
                        item["categoria"],
                        item["subcategoria"],
                        float(to_dec(item["valor"])),
                        item.get("detalhe_componente") or m["historico_banco"],
                    ),
                )
                count_rateios += 1
            count_movs += 1

        recalculate_all(conn)
        conn.close()
        return {
            "sucesso": True,
            "movimentos_classificados": count_movs,
            "linhas_rateio_geradas": count_rateios,
        }

    def _get_extrato_list(self, qs):
        mes = qs.get("mes", ["ALL"])[0]
        status_rateio = qs.get("status_rateio", ["ALL"])[0]
        busca = (qs.get("busca", [""])[0] or "").strip().upper()
        fornecedor = (qs.get("fornecedor", [""])[0] or "").strip()
        id_lanc_exact = (qs.get("id_lanc", [""])[0] or "").strip().upper()
        limit = int(qs.get("limit", ["300"])[0])
        offset = int(qs.get("offset", ["0"])[0])

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT * FROM extrato ORDER BY ordem ASC")
        all_ext = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM rateios ORDER BY id_rateio ASC")
        all_rat = [dict(r) for r in cur.fetchall()]
        conn.close()

        rat_map = {}
        for r in all_rat:
            rat_map.setdefault(r["id_lanc"], []).append(r)

        filtered = []
        for e in all_ext:
            if id_lanc_exact and e["id_lanc"].upper() != id_lanc_exact:
                continue
            if mes != "ALL" and mes.isdigit() and e["mes"] != int(mes):
                continue
            if status_rateio != "ALL":
                if status_rateio == "DIVERGENCIA" and e["status_rateio"] != "DIVERGÊNCIA":
                    continue
                elif status_rateio == "NAO_CLASSIFICADO" and e["status_rateio"] not in ("NÃO CLASSIFICADO", "PENDENTE DE RATEIO"):
                    continue
                elif status_rateio == "RATEIO_OK" and e["status_rateio"] != "RATEIO OK":
                    continue
                elif status_rateio == "DESCONSIDERADO" and e["status_rateio"] != "DESCONSIDERADO":
                    continue
                elif status_rateio not in ("DIVERGENCIA", "NAO_CLASSIFICADO", "RATEIO_OK", "DESCONSIDERADO") and e["status_rateio"] != status_rateio:
                    continue
            if fornecedor and e["fornecedor_canonico"] != fornecedor:
                continue
            if busca:
                rateio_terms = " ".join(
                    f"{r.get('categoria') or ''} {r.get('subcategoria') or ''}"
                    for r in rat_map.get(e["id_lanc"], [])
                )
                hay = f"{e['id_lanc']} {e['historico_banco']} {e['fornecedor_favorecido']} {e['fornecedor_canonico']} {e['documento']} {e['observacao']} {rateio_terms}".upper()
                if busca not in hay:
                    continue

            e_copy = dict(e)
            e_copy["rateios"] = rat_map.get(e["id_lanc"], [])
            filtered.append(e_copy)

        total_filtered = len(filtered)
        paginated = filtered[offset : offset + limit]
        return {
            "total": total_filtered,
            "offset": offset,
            "limit": limit,
            "itens": paginated,
        }

    def _salvar_rateio(self, body):
        """
        Salva alterações de um movimento e suas N linhas de rateio.
        Bloqueia rigorosamente caso ABS(diferenca) > 0.005!
        """
        id_lanc = (body.get("id_lanc") or "").strip()
        if not id_lanc:
            raise ValueError("ID_LANC é obrigatório.")

        rateios_in = body.get("rateios", [])
        if not rateios_in:
            raise ValueError("O lançamento deve possuir pelo menos 1 linha de rateio.")

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM extrato WHERE id_lanc = ?", (id_lanc,))
        row = cur.fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Lançamento {id_lanc} não encontrado no extrato.")
        ext = dict(row)

        # Optional updates to extrato fields
        data_iso = (body.get("data") or ext["data"] or "").strip()
        tipo_mov = (body.get("tipo_movimentacao") or ext["tipo_movimentacao"] or "SAÍDA").strip()
        tipo_pag = (body.get("tipo_pagamento") or ext["tipo_pagamento"] or "PIX").strip()
        forn = body.get("fornecedor_favorecido", ext["fornecedor_favorecido"])
        doc = body.get("documento", ext["documento"])
        obs = body.get("observacao", ext["observacao"])
        st_conc = body.get("status_conciliacao", ext["status_conciliacao"] or "Conciliado")
        hist = body.get("historico_banco", ext["historico_banco"])
        descons_flag = 1 if body.get("desconsiderar_rateio") else 0

        if "valor_movimento" in body and body["valor_movimento"] is not None:
            v_mov = to_dec(body["valor_movimento"])
            ent = v_mov if tipo_mov == "ENTRADA" else Decimal("0.00")
            sai = v_mov if tipo_mov == "SAÍDA" else Decimal("0.00")
            apl = v_mov if tipo_mov == "APLICAÇÃO" else Decimal("0.00")
            res = v_mov if tipo_mov == "RESGATE" else Decimal("0.00")
        else:
            ent = to_dec(body.get("entrada", ext["entrada"]))
            sai = to_dec(body.get("saida", ext["saida"]))
            apl = to_dec(body.get("aplicacao", ext["aplicacao"]))
            res = to_dec(body.get("resgate", ext["resgate"]))
        valor_banco = (ent + sai + apl + res).quantize(TWO_PLACES)

        if descons_flag == 1:
            cur.execute(
                """
                UPDATE extrato
                SET data = ?, tipo_movimentacao = ?, tipo_pagamento = ?,
                    historico_banco = ?, fornecedor_favorecido = ?, documento = ?,
                    entrada = ?, saida = ?, aplicacao = ?, resgate = ?,
                    status_conciliacao = ?, observacao = ?, desconsiderar_rateio = 1
                WHERE id_lanc = ?
                """,
                (data_iso, tipo_mov, tipo_pag, hist, forn, doc, float(ent), float(sai), float(apl), float(res), st_conc, obs, id_lanc),
            )
            cur.execute("DELETE FROM rateios WHERE id_lanc = ?", (id_lanc,))
            cur.execute(
                """
                INSERT INTO rateios (
                    id_lanc, categoria, subcategoria, valor,
                    detalhe_componente, origem_classificacao
                ) VALUES (?, 'DESCONSIDERADO NO RATEIO', 'Não considerado no Rateio / DRE', ?, ?, 'DESCONSIDERADO')
                """,
                (id_lanc, float(valor_banco), hist),
            )
            recalculate_all(conn)
            conn.close()
            return {"sucesso": True, "id_lanc": id_lanc, "total_rateado": float(valor_banco), "diferenca": 0.0, "status_rateio": "DESCONSIDERADO"}

        soma_rateios = Decimal("0.00")
        validated_rateios = []
        for idx, r in enumerate(rateios_in, start=1):
            v = to_dec(r.get("valor", 0))
            if v <= Decimal("0.00"):
                conn.close()
                raise ValueError(f"Linha {idx} do rateio possui valor inválido (R$ {v}).")
            cat = (r.get("categoria") or "").strip()
            sub = (r.get("subcategoria") or "").strip()
            if not cat or not sub:
                conn.close()
                raise ValueError(f"Linha {idx} do rateio requer Categoria e Subcategoria.")
            if cat != "DESCONSIDERADO NO RATEIO" and sub not in PLANO_DE_CONTAS.get(cat, []):
                conn.close()
                raise ValueError(f"Par Categoria '{cat}' + Subcategoria '{sub}' é incompatível com o Plano de Contas.")
            soma_rateios = (soma_rateios + v).quantize(TWO_PLACES)
            validated_rateios.append({
                "categoria": cat,
                "subcategoria": sub,
                "valor": float(v),
                "detalhe_componente": (r.get("detalhe_componente") or hist).strip(),
                "origem_classificacao": r.get("origem_classificacao") or "CONFIRMADO",
            })

        dif = (valor_banco - soma_rateios).quantize(TWO_PLACES)
        if abs(dif) > TOLERANCE:
            conn.close()
            raise ValueError(
                f"Bloqueio de Fidelidade Contábil: Valor do Banco (R$ {valor_banco}) difere do Total Rateado (R$ {soma_rateios}) em R$ {dif}. Tolerância zero a divergências de centavos!"
            )

        cur.execute(
            """
            UPDATE extrato
            SET data = ?, tipo_movimentacao = ?, tipo_pagamento = ?,
                historico_banco = ?, fornecedor_favorecido = ?, documento = ?,
                entrada = ?, saida = ?, aplicacao = ?, resgate = ?,
                status_conciliacao = ?, observacao = ?, desconsiderar_rateio = 0
            WHERE id_lanc = ?
            """,
            (data_iso, tipo_mov, tipo_pag, hist, forn, doc, float(ent), float(sai), float(apl), float(res), st_conc, obs, id_lanc),
        )

        cur.execute("DELETE FROM rateios WHERE id_lanc = ?", (id_lanc,))
        for vr in validated_rateios:
            cur.execute(
                """
                INSERT INTO rateios (
                    id_lanc, categoria, subcategoria, valor,
                    detalhe_componente, origem_classificacao
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (id_lanc, vr["categoria"], vr["subcategoria"], vr["valor"], vr["detalhe_componente"], vr["origem_classificacao"]),
            )

        recalculate_all(conn)
        conn.close()
        return {"sucesso": True, "id_lanc": id_lanc, "total_rateado": float(soma_rateios), "diferenca": 0.0}

    def _editar_lancamento(self, body):
        """
        Edita todos os campos cadastrais/financeiros de um lançamento no extrato
        (data, tipo_movimentacao, tipo_pagamento, valor, historico_banco, fornecedor_favorecido,
         documento, status_conciliacao, observacao, desconsiderar_rateio).
        """
        id_lanc = (body.get("id_lanc") or "").strip()
        if not id_lanc:
            raise ValueError("ID_LANC é obrigatório.")

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM extrato WHERE id_lanc = ?", (id_lanc,))
        row = cur.fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Lançamento {id_lanc} não encontrado.")
        ext = dict(row)

        data_iso = (body.get("data") or ext["data"] or "").strip()
        tipo_mov = (body.get("tipo_movimentacao") or ext["tipo_movimentacao"] or "SAÍDA").strip()
        tipo_pag = (body.get("tipo_pagamento") or ext["tipo_pagamento"] or "PIX").strip()
        hist = (body.get("historico_banco") if "historico_banco" in body else ext["historico_banco"]) or ""
        forn = (body.get("fornecedor_favorecido") if "fornecedor_favorecido" in body else ext["fornecedor_favorecido"]) or ""
        doc = (body.get("documento") if "documento" in body else ext["documento"]) or ""
        st_conc = (body.get("status_conciliacao") if "status_conciliacao" in body else ext["status_conciliacao"]) or "Conciliado"
        obs = (body.get("observacao") if "observacao" in body else ext["observacao"]) or ""
        descons = 1 if body.get("desconsiderar_rateio") else 0

        old_val = to_dec(ext["entrada"]) + to_dec(ext["saida"]) + to_dec(ext["aplicacao"]) + to_dec(ext["resgate"])
        novo_val = to_dec(body.get("valor", old_val))
        if novo_val <= Decimal("0.00"):
            conn.close()
            raise ValueError("O valor do lançamento deve ser maior que zero.")

        ent = novo_val if tipo_mov == "ENTRADA" else Decimal("0.00")
        sai = novo_val if tipo_mov == "SAÍDA" else Decimal("0.00")
        apl = novo_val if tipo_mov == "APLICAÇÃO" else Decimal("0.00")
        res = novo_val if tipo_mov == "RESGATE" else Decimal("0.00")

        cur.execute(
            """
            UPDATE extrato
            SET data = ?, tipo_movimentacao = ?, tipo_pagamento = ?,
                historico_banco = ?, fornecedor_favorecido = ?, documento = ?,
                entrada = ?, saida = ?, aplicacao = ?, resgate = ?,
                status_conciliacao = ?, observacao = ?, desconsiderar_rateio = ?
            WHERE id_lanc = ?
            """,
            (data_iso, tipo_mov, tipo_pag, hist, forn, doc, float(ent), float(sai), float(apl), float(res), st_conc, obs, descons, id_lanc),
        )

        cur.execute("SELECT * FROM rateios WHERE id_lanc = ? ORDER BY id_rateio ASC", (id_lanc,))
        rat_rows = [dict(r) for r in cur.fetchall()]

        if descons == 1:
            cur.execute("DELETE FROM rateios WHERE id_lanc = ?", (id_lanc,))
            cur.execute(
                """
                INSERT INTO rateios (
                    id_lanc, categoria, subcategoria, valor,
                    detalhe_componente, origem_classificacao
                ) VALUES (?, 'DESCONSIDERADO NO RATEIO', 'Não considerado no Rateio / DRE', ?, ?, 'DESCONSIDERADO')
                """,
                (id_lanc, float(novo_val), hist),
            )
        else:
            # If it was previously desconsiderado, reset to empty category or auto-suggest
            if len(rat_rows) == 1 and (rat_rows[0]["categoria"] or "") == "DESCONSIDERADO NO RATEIO":
                cur.execute(
                    "UPDATE rateios SET categoria = '', subcategoria = '', valor = ?, detalhe_componente = ?, origem_classificacao = 'PENDENTE' WHERE id_rateio = ?",
                    (float(novo_val), hist, rat_rows[0]["id_rateio"]),
                )
            elif len(rat_rows) == 1:
                # Automatically sync the single rateio line value with the updated bank value
                cur.execute(
                    "UPDATE rateios SET valor = ? WHERE id_rateio = ?",
                    (float(novo_val), rat_rows[0]["id_rateio"]),
                )

        recalculate_all(conn)
        conn.close()
        return {"sucesso": True, "id_lanc": id_lanc, "valor": float(novo_val), "desconsiderar_rateio": bool(descons)}

    def _desconsiderar_no_rateio(self, body):
        """
        Marca ou desmarca 1 ou mais lançamentos como 'Desconsiderar no rateio'
        (ex: estornos como BAN-00034/00035 TIM S/A, PIX rejeitado BAN-00781/00782, transferências internas).
        """
        ids_lanc = body.get("ids_lanc", [])
        if body.get("id_lanc"):
            ids_lanc.append(body["id_lanc"])
        desconsiderar = bool(body.get("desconsiderar", True))

        if not ids_lanc:
            raise ValueError("Informe ao menos um ID_LANC.")

        conn = get_conn()
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in ids_lanc)
        cur.execute(f"SELECT * FROM extrato WHERE id_lanc IN ({placeholders})", ids_lanc)
        movs = [dict(r) for r in cur.fetchall()]

        for m in movs:
            id_l = m["id_lanc"]
            val_b = to_dec(m["entrada"]) + to_dec(m["saida"]) + to_dec(m["aplicacao"]) + to_dec(m["resgate"])
            hist = m["historico_banco"] or ""
            if desconsiderar:
                cur.execute(
                    "UPDATE extrato SET desconsiderar_rateio = 1, status_conciliacao = 'Conciliado' WHERE id_lanc = ?",
                    (id_l,),
                )
                cur.execute("DELETE FROM rateios WHERE id_lanc = ?", (id_l,))
                cur.execute(
                    """
                    INSERT INTO rateios (
                        id_lanc, categoria, subcategoria, valor,
                        detalhe_componente, origem_classificacao
                    ) VALUES (?, 'DESCONSIDERADO NO RATEIO', 'Não considerado no Rateio / DRE', ?, ?, 'DESCONSIDERADO')
                    """,
                    (id_l, float(val_b), hist),
                )
            else:
                cur.execute("UPDATE extrato SET desconsiderar_rateio = 0 WHERE id_lanc = ?", (id_l,))
                cur.execute("DELETE FROM rateios WHERE id_lanc = ?", (id_l,))
                cur.execute(
                    """
                    INSERT INTO rateios (
                        id_lanc, categoria, subcategoria, valor,
                        detalhe_componente, origem_classificacao
                    ) VALUES (?, '', '', ?, ?, 'PENDENTE')
                    """,
                    (id_l, float(val_b), hist),
                )

        recalculate_all(conn)
        conn.close()
        return {
            "sucesso": True,
            "afetados": len(movs),
            "desconsiderar": desconsiderar,
            "mensagem": f"{len(movs)} lançamento(s) {'desconsiderado(s) no rateio' if desconsiderar else 'reativado(s) para classificação no rateio'}!",
        }

    def _excluir_lancamento(self, body):
        id_lanc = (body.get("id_lanc") or "").strip()
        if not id_lanc:
            raise ValueError("ID_LANC é obrigatório.")
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM rateios WHERE id_lanc = ?", (id_lanc,))
        cur.execute("DELETE FROM extrato WHERE id_lanc = ?", (id_lanc,))
        recalculate_all(conn)
        conn.close()
        return {"sucesso": True, "id_lanc": id_lanc}

    def _corrigir_ban00697(self, body):
        """
        Resolve imediatamente a divergência de -R$ 0,03 no lançamento BAN-00697 (13/07/2026 - I F DA SILVA & CIA LTDA):
        Extrato Saída = R$ 11.206,30 vs. Soma de 6 linhas no Rateio = R$ 11.206,33.
        Ajusta a linha de Serviço de enfermagem (ou extras) em -R$ 0,03 para fechar exatamente em R$ 11.206,30.
        """
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM rateios WHERE id_lanc = 'BAN-00697' ORDER BY id_rateio ASC")
        rows = [dict(r) for r in cur.fetchall()]
        if not rows:
            conn.close()
            raise ValueError("Rateios de BAN-00697 não encontrados.")

        # Find the row with 3886.36 or 600.00 and subtract 0.03 so total equals 11206.30
        soma_atual = sum((to_dec(r["valor"]) for r in rows), Decimal("0.00"))
        alvo = Decimal("11206.30")
        ajuste = (alvo - soma_atual).quantize(TWO_PLACES)

        if abs(ajuste) > Decimal("0.00"):
            target_row = rows[-1]
            for r in rows:
                if to_dec(r["valor"]) == Decimal("3886.36") or to_dec(r["valor"]) == Decimal("600.00"):
                    target_row = r
            novo_val = (to_dec(target_row["valor"]) + ajuste).quantize(TWO_PLACES)
            cur.execute(
                "UPDATE rateios SET valor = ?, origem_classificacao = 'CONFIRMADO' WHERE id_rateio = ?",
                (float(novo_val), target_row["id_rateio"]),
            )
            cur.execute("UPDATE rateios SET origem_classificacao = 'CONFIRMADO' WHERE id_lanc = 'BAN-00697'")

        recalculate_all(conn)
        conn.close()
        return {
            "sucesso": True,
            "id_lanc": "BAN-00697",
            "mensagem": "Divergência de -R$ 0,03 em BAN-00697 corrigida com sucesso! Soma dos rateios agora fecha exatamente em R$ 11.206,30.",
        }

    def _criar_novo_movimento(self, body):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT MAX(ordem) as max_o FROM extrato")
        r_max = cur.fetchone()
        prox_ordem = (r_max["max_o"] or 1061) + 1
        if prox_ordem > 2999:
            conn.close()
            raise ValueError("Capacidade máxima do modelo atingida (BAN-02999).")

        id_lanc = f"BAN-{prox_ordem:05d}"
        data_iso = (body.get("data") or "2026-10-21").strip()
        mes = int(data_iso.split("-")[1]) if "-" in data_iso else 10
        tipo_pag = (body.get("tipo_pagamento") or "PIX").strip()
        tipo_mov = (body.get("tipo_movimentacao") or "SAÍDA").strip()
        hist = (body.get("historico_banco") or "").strip()
        forn = (body.get("fornecedor_favorecido") or "").strip()
        if not forn:
            forn = infer_missing_supplier(hist)
        doc = (body.get("documento") or "").strip()
        obs = (body.get("observacao") or "").strip()

        valor = to_dec(body.get("valor", 0))
        if valor <= Decimal("0.00"):
            conn.close()
            raise ValueError("O valor do movimento deve ser maior que zero.")

        ent = valor if tipo_mov == "ENTRADA" else Decimal("0.00")
        sai = valor if tipo_mov == "SAÍDA" else Decimal("0.00")
        apl = valor if tipo_mov == "APLICAÇÃO" else Decimal("0.00")
        res = valor if tipo_mov == "RESGATE" else Decimal("0.00")

        cur.execute(
            """
            INSERT INTO extrato (
                id_lanc, ordem, data, mes, competencia_extraida,
                tipo_pagamento, tipo_movimentacao, historico_banco,
                fornecedor_favorecido, fornecedor_canonico, documento,
                entrada, saida, aplicacao, resgate,
                status_conciliacao, observacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Conciliado', ?)
            """,
            (
                id_lanc, prox_ordem, data_iso, mes, f"{mes:02d}/2026",
                tipo_pag, tipo_mov, hist,
                forn, get_canonical_supplier(forn, hist), doc,
                float(ent), float(sai), float(apl), float(res),
                obs,
            ),
        )

        rateios_in = body.get("rateios", [])
        if not rateios_in:
            # Generate automatic suggestion
            sug = suggest_for_movement({
                "id_lanc": id_lanc,
                "historico_banco": hist,
                "fornecedor_favorecido": forn,
                "tipo_movimentacao": tipo_mov,
                "tipo_pagamento": tipo_pag,
                "entrada": float(ent),
                "saida": float(sai),
                "aplicacao": float(apl),
                "resgate": float(res),
            })
            rateios_in = sug["rateios_sugeridos"]

        soma_rat = sum((to_dec(r["valor"]) for r in rateios_in), Decimal("0.00"))
        if abs(valor - soma_rat) > TOLERANCE:
            conn.close()
            raise ValueError(f"Soma dos rateios (R$ {soma_rat}) difere do valor do movimento (R$ {valor}).")

        for r in rateios_in:
            cur.execute(
                """
                INSERT INTO rateios (
                    id_lanc, categoria, subcategoria, valor,
                    detalhe_componente, origem_classificacao
                ) VALUES (?, ?, ?, ?, ?, 'CONFIRMADO')
                """,
                (
                    id_lanc,
                    r["categoria"],
                    r["subcategoria"],
                    float(to_dec(r["valor"])),
                    r.get("detalhe_componente") or hist,
                ),
            )

        recalculate_all(conn)
        conn.close()
        return {"sucesso": True, "id_lanc": id_lanc, "ordem": prox_ordem}

    def _gerar_template(self, body):
        tipo = (body.get("template") or "FERRONEFRO").upper()
        valor = to_dec(body.get("valor", 0))
        fornecedor = body.get("fornecedor") or ""
        historico = body.get("historico") or ""

        if tipo == "FERRONEFRO":
            itens = build_ferronefro_split(valor, historico or "I F DA SILVA & CIA LTDA")
        elif tipo == "SOCIOS":
            itens = build_socio_split(valor, fornecedor or "SÓCIO", historico or "PLANTÕES MÉDICOS + DISTRIBUIÇÃO DE LUCROS")
        elif tipo == "NOTAS_MISTAS":
            itens = build_notas_mistas_split(valor, fornecedor or "FORNECEDOR", historico or "NOTA FISCAL MISTA INSUMOS HD")
        else:
            raise ValueError(f"Template desconhecido: {tipo}")

        return {"sucesso": True, "template": tipo, "valor_total": float(valor), "itens": itens}

    def _salvar_parametros(self, body):
        conn = get_conn()
        cur = conn.cursor()
        for k in ("saldo_inicial_cc", "saldo_inicial_aplicacao", "rendimentos_aplicacao"):
            if k in body:
                v = str(to_dec(body[k]))
                cur.execute("UPDATE config_parametros SET valor = ? WHERE chave = ?", (v, k))
        recalculate_all(conn)
        conn.close()
        return {"sucesso": True}


def run_server(port: int = 8090):
    ensure_db_initialized()
    conn = get_conn()
    ensure_tax_schema(conn)
    ensure_payment_schema(conn)
    ensure_auth_schema(conn)
    conn.close()
    bind_host = os.environ.get("BIORENAL_BIND_HOST", "127.0.0.1")
    cert_path = os.environ.get("BIORENAL_TLS_CERT", "")
    key_path = os.environ.get("BIORENAL_TLS_KEY", "")
    is_lan = bind_host not in ("127.0.0.1", "localhost", "::1")
    if is_lan and (not cert_path or not key_path or not os.environ.get("BIORENAL_LAN_IP")):
        raise RuntimeError("Acesso pela rede exige certificado HTTPS, chave e BIORENAL_LAN_IP.")
    server_address = (bind_host, port)
    httpd = ThreadingHTTPServer(server_address, BiorenalRequestHandler)
    httpd.is_tls = bool(cert_path and key_path)
    if httpd.is_tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    scheme = "https" if httpd.is_tls else "http"
    print(f"[BIORENAL 2026] Servidor Full-Stack iniciado!")
    print(f" -> Acesso Local (Neste PC): {scheme}://127.0.0.1:{port}")
    if bind_host not in ("127.0.0.1", "localhost", "::1"):
        print(f" -> Acesso pela rede: https://{os.environ['BIORENAL_LAN_IP']}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    run_server(p)
