"""Bloque 14 — Cuentas de usuario (registro y login).

Contraseñas cifradas con PBKDF2-HMAC-SHA256 + salt aleatorio por usuario. Nunca
se guarda la contraseña en claro. Pensado para una app casual entre amigos.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import secrets
import sqlite3

PBKDF2_ROUNDS = 200_000
SESSION_DAYS = 30


class UserError(RuntimeError):
    pass


def _hash(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS)
    return dk.hex()


def _norm(s: str) -> str:
    """Normaliza una respuesta de recuperación (tolerante a mayúsculas/espacios)."""
    return (s or "").strip().lower()


def _valid_username(u: str) -> bool:
    return bool(u) and 3 <= len(u) <= 20 and u.replace("_", "").isalnum()


def create_user(conn: sqlite3.Connection, username: str, password: str,
                recovery_question: str | None = None, recovery_answer: str | None = None) -> int:
    username = (username or "").strip().lower()
    if not _valid_username(username):
        raise UserError("El usuario debe tener 3-20 caracteres (letras, números o _).")
    if len(password or "") < 4:
        raise UserError("La contraseña debe tener al menos 4 caracteres.")
    if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise UserError("Ese usuario ya existe. Elige otro o inicia sesión.")
    salt = os.urandom(16).hex()
    ra_hash = _hash(_norm(recovery_answer), salt) if recovery_answer else None
    conn.execute(
        """INSERT INTO users (username, password_hash, salt, created_at,
                              recovery_question, recovery_answer_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (username, _hash(password, salt), salt,
         dt.datetime.now().isoformat(timespec="seconds"),
         (recovery_question or "").strip() or None, ra_hash),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    return int(row["id"])


# ---- Recuperación de contraseña (pregunta secreta, sin email) ------------
def get_recovery_question(conn: sqlite3.Connection, username: str) -> str | None:
    username = (username or "").strip().lower()
    row = conn.execute(
        "SELECT recovery_question FROM users WHERE username=?", (username,)).fetchone()
    return row["recovery_question"] if row and row["recovery_question"] else None


def reset_password(conn: sqlite3.Connection, username: str,
                   recovery_answer: str, new_password: str) -> bool:
    """Cambia la contraseña si la respuesta de recuperación es correcta."""
    username = (username or "").strip().lower()
    row = conn.execute(
        "SELECT id, salt, recovery_answer_hash FROM users WHERE username=?", (username,)
    ).fetchone()
    if not row or not row["recovery_answer_hash"]:
        return False
    if _hash(_norm(recovery_answer), row["salt"]) != row["recovery_answer_hash"]:
        return False
    if len(new_password or "") < 4:
        raise UserError("La nueva contraseña debe tener al menos 4 caracteres.")
    conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                 (_hash(new_password, row["salt"]), int(row["id"])))
    conn.commit()
    return True


# ---- Sesiones recordadas (token) -----------------------------------------
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    """Crea un token de sesión (se guarda su hash) y lo devuelve en claro."""
    token = secrets.token_urlsafe(32)
    exp = (dt.datetime.now() + dt.timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    conn.execute(
        "INSERT OR REPLACE INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (_token_hash(token), int(user_id), exp),
    )
    conn.commit()
    return token


def validate_session(conn: sqlite3.Connection, token: str) -> int | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT user_id, expires_at FROM sessions WHERE token_hash=?", (_token_hash(token),)
    ).fetchone()
    if not row:
        return None
    try:
        if dt.datetime.fromisoformat(row["expires_at"]) < dt.datetime.now():
            delete_session(conn, token)
            return None
    except (ValueError, TypeError):
        pass
    return int(row["user_id"])


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    if not token:
        return
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
    conn.commit()


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> int | None:
    username = (username or "").strip().lower()
    row = conn.execute(
        "SELECT id, password_hash, salt FROM users WHERE username=?", (username,)
    ).fetchone()
    if not row:
        return None
    if _hash(password, row["salt"]) == row["password_hash"]:
        return int(row["id"])
    return None


def get_username(conn: sqlite3.Connection, user_id: int) -> str | None:
    row = conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    return row["username"] if row else None
