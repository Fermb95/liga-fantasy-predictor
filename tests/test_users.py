"""Tests de cuentas de usuario (Bloque 14)."""
import pytest

from src import db, users


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "u.db")
    yield c
    c.close()


def test_registro_y_login(conn):
    uid = users.create_user(conn, "Fernando", "clave123")
    assert uid > 0
    assert users.authenticate(conn, "fernando", "clave123") == uid   # usuario en minúsculas
    assert users.authenticate(conn, "fernando", "mala") is None
    assert users.authenticate(conn, "noexiste", "x") is None
    assert users.get_username(conn, uid) == "fernando"


def test_no_guarda_contraseña_en_claro(conn):
    users.create_user(conn, "pepe", "secreto99")
    row = conn.execute("SELECT password_hash FROM users WHERE username='pepe'").fetchone()
    assert "secreto99" not in row["password_hash"]
    assert len(row["password_hash"]) >= 32


def test_usuario_duplicado(conn):
    users.create_user(conn, "ana", "clave1")
    with pytest.raises(users.UserError):
        users.create_user(conn, "ANA", "clave2")     # mismo nombre (case-insensitive)


def test_validaciones(conn):
    with pytest.raises(users.UserError):
        users.create_user(conn, "ab", "clave1")       # nombre corto
    with pytest.raises(users.UserError):
        users.create_user(conn, "juan", "123")        # contraseña corta


def test_dos_usuarios_distintos(conn):
    a = users.create_user(conn, "uno", "clave1")
    b = users.create_user(conn, "dos", "clave2")
    assert a != b
