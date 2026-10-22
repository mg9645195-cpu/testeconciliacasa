"""Local user accounts and short-lived browser sessions for the BioRenal LAN app."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import scrypt, sha256
import hmac
import re
import secrets
import sqlite3
import time

from database import get_conn

SESSION_SECONDS = 12 * 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 5
ROLES = ("ADMIN", "OPERADOR", "CONSULTA")
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")


@contextmanager
def auth_conn():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_auth_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS auth_users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL UNIQUE COLLATE NOCASE,
      display_name TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('ADMIN','OPERADOR','CONSULTA')),
      password_hash TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 1,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS auth_sessions (
      token_hash TEXT PRIMARY KEY,
      csrf_token TEXT NOT NULL,
      user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
      expires_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires ON auth_sessions(expires_at);
    CREATE TABLE IF NOT EXISTS auth_failures (
      client_ip TEXT PRIMARY KEY,
      count INTEGER NOT NULL,
      first_at INTEGER NOT NULL
    );
    """)


def is_configured() -> bool:
    with auth_conn() as conn:
        ensure_auth_schema(conn)
        return conn.execute("SELECT EXISTS(SELECT 1 FROM auth_users)").fetchone()[0] == 1


def _validate_username(username: str) -> str:
    username = str(username or "").strip().lower()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("Usuário deve ter 3 a 32 letras, números, ponto, hífen ou sublinhado.")
    return username


def _validate_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 12 or len(password) > 128:
        raise ValueError("A senha deve conter de 12 a 128 caracteres.")
    return password


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def _password_matches(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = stored.split("$")
        if algorithm != "scrypt":
            return False
        calculated = scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                            n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(calculated, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def setup_admin(body: dict) -> dict:
    username = _validate_username(body.get("username"))
    display_name = str(body.get("display_name") or "").strip()[:80]
    password = _validate_password(body.get("password"))
    if not display_name:
        raise ValueError("Informe o nome que aparecerá no sistema.")
    now = int(time.time())
    with auth_conn() as conn:
        ensure_auth_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT EXISTS(SELECT 1 FROM auth_users)").fetchone()[0]:
            raise ValueError("O administrador inicial já foi cadastrado.")
        conn.execute("INSERT INTO auth_users(username,display_name,role,password_hash,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                     (username, display_name, "ADMIN", _password_hash(password), now, now))
    return {"sucesso": True}


def login(body: dict, client_ip: str) -> tuple[dict, str]:
    username = str(body.get("username") or "").strip().lower()
    password = body.get("password")
    if not isinstance(password, str) or len(password) > 128:
        raise ValueError("Usuário ou senha inválidos.")
    now = int(time.time())
    with auth_conn() as conn:
        ensure_auth_schema(conn)
        failure = conn.execute("SELECT count,first_at FROM auth_failures WHERE client_ip=?", (client_ip,)).fetchone()
        if failure and now - failure["first_at"] < LOGIN_WINDOW_SECONDS and failure["count"] >= MAX_FAILURES:
            raise ValueError("Muitas tentativas. Aguarde 15 minutos e tente novamente.")
        user = conn.execute("SELECT * FROM auth_users WHERE username=? AND active=1", (username,)).fetchone()
        if not user or not _password_matches(password, user["password_hash"]):
            if not failure or now - failure["first_at"] >= LOGIN_WINDOW_SECONDS:
                conn.execute("INSERT INTO auth_failures(client_ip,count,first_at) VALUES (?,1,?) ON CONFLICT(client_ip) DO UPDATE SET count=1,first_at=excluded.first_at", (client_ip, now))
            else:
                conn.execute("UPDATE auth_failures SET count=count+1 WHERE client_ip=?", (client_ip,))
            conn.commit()
            raise ValueError("Usuário ou senha inválidos.")
        conn.execute("DELETE FROM auth_failures WHERE client_ip=?", (client_ip,))
        conn.execute("DELETE FROM auth_sessions WHERE expires_at<?", (now,))
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO auth_sessions(token_hash,csrf_token,user_id,expires_at) VALUES (?,?,?,?)",
                     (sha256(token.encode()).hexdigest(), csrf, user["id"], now + SESSION_SECONDS))
        return ({"sucesso": True, "usuario": _public_user(user), "csrf_token": csrf}, token)


def _public_user(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "username": row["username"],
            "display_name": row["display_name"], "role": row["role"]}


def current_session(raw_token: str) -> dict | None:
    if not raw_token or len(raw_token) > 128:
        return None
    with auth_conn() as conn:
        ensure_auth_schema(conn)
        row = conn.execute("""SELECT s.csrf_token,s.expires_at,u.id,u.username,u.display_name,u.role
            FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""",
            (sha256(raw_token.encode()).hexdigest(), int(time.time()))).fetchone()
        if not row:
            return None
        return {"usuario": _public_user(row), "csrf_token": row["csrf_token"]}


def logout(raw_token: str) -> None:
    if raw_token and len(raw_token) <= 128:
        with auth_conn() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (sha256(raw_token.encode()).hexdigest(),))


def list_users() -> list[dict]:
    with auth_conn() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT id,username,display_name,role,active,created_at,updated_at FROM auth_users ORDER BY id")]


def save_user(body: dict, acting_user_id: int) -> dict:
    user_id = int(body.get("id") or 0)
    username = _validate_username(body.get("username"))
    display_name = str(body.get("display_name") or "").strip()[:80]
    role = str(body.get("role") or "").upper()
    active = int(bool(body.get("active", True)))
    password = body.get("password") or ""
    if not display_name or role not in ROLES:
        raise ValueError("Informe nome e perfil de acesso válidos.")
    if user_id == acting_user_id and (role != "ADMIN" or not active):
        raise ValueError("Não é possível remover seu próprio acesso de administrador.")
    now = int(time.time())
    with auth_conn() as conn:
        if user_id:
            current = conn.execute("SELECT * FROM auth_users WHERE id=?", (user_id,)).fetchone()
            if not current:
                raise ValueError("Usuário não encontrado.")
            if current["role"] == "ADMIN" and (role != "ADMIN" or not active):
                admins = conn.execute("SELECT COUNT(*) FROM auth_users WHERE role='ADMIN' AND active=1").fetchone()[0]
                if admins <= 1:
                    raise ValueError("É necessário manter pelo menos um administrador ativo.")
            if password:
                _validate_password(password)
                hashed = _password_hash(password)
                conn.execute("UPDATE auth_users SET username=?,display_name=?,role=?,active=?,password_hash=?,updated_at=? WHERE id=?",
                             (username, display_name, role, active, hashed, now, user_id))
                conn.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
            else:
                conn.execute("UPDATE auth_users SET username=?,display_name=?,role=?,active=?,updated_at=? WHERE id=?",
                             (username, display_name, role, active, now, user_id))
                if current["role"] != role or not active:
                    conn.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
        else:
            _validate_password(password)
            cursor = conn.execute("INSERT INTO auth_users(username,display_name,role,password_hash,active,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                                  (username, display_name, role, _password_hash(password), active, now, now))
            user_id = cursor.lastrowid
    return {"sucesso": True, "id": user_id}


def change_password(body: dict, user_id: int) -> dict:
    old = str(body.get("current_password") or "")
    new = _validate_password(body.get("new_password"))
    with auth_conn() as conn:
        user = conn.execute("SELECT password_hash FROM auth_users WHERE id=?", (user_id,)).fetchone()
        if not user or not _password_matches(old, user["password_hash"]):
            raise ValueError("Senha atual incorreta.")
        conn.execute("UPDATE auth_users SET password_hash=?,updated_at=? WHERE id=?",
                     (_password_hash(new), int(time.time()), user_id))
        conn.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
    return {"sucesso": True}
