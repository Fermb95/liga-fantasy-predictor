"""Bloque 14 — Cuentas de usuario (registro y login).

Contraseñas cifradas con PBKDF2-HMAC-SHA256 + salt aleatorio por usuario. Nunca
se guarda la contraseña en claro. Pensado para una app casual entre amigos.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import sqlite3

PBKDF2_ROUNDS = 200_000


class UserError(RuntimeError):
    pass


def _hash(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS)
    return dk.hex()


def _valid_username(u: str) -> bool:
    return bool(u) and 3 <= len(u) <= 20 and u.replace("_", "").isalnum()


def create_user(conn: sqlite3.Connection, username: str, password: str) -> int:
    username = (username or "").strip().lower()
    if not _valid_username(username):
        raise UserError("El usuario debe tener 3-20 caracteres (letras, números o _).")
    if len(password or "") < 4:
        raise UserError("La contraseña debe tener al menos 4 caracteres.")
    if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise UserError("Ese usuario ya existe. Elige otro o inicia sesión.")
    salt = os.urandom(16).hex()
    conn.execute(
        "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
        (username, _hash(password, salt), salt, dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    return int(row["id"])


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
