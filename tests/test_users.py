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


# ---- Recuperación de contraseña ----
def test_recuperar_contrasena(conn):
    users.create_user(conn, "ferran", "vieja",
                      recovery_question="¿Tu equipo?", recovery_answer="Barça")
    assert users.get_recovery_question(conn, "ferran") == "¿Tu equipo?"
    # respuesta correcta (tolerante a mayúsculas/espacios) -> cambia la clave
    assert users.reset_password(conn, "ferran", "  barça ", "nueva") is True
    assert users.authenticate(conn, "ferran", "nueva")
    assert users.authenticate(conn, "ferran", "vieja") is None


def test_recuperar_respuesta_incorrecta(conn):
    users.create_user(conn, "ferran", "vieja",
                      recovery_question="¿Tu equipo?", recovery_answer="Barça")
    assert users.reset_password(conn, "ferran", "Madrid", "nueva") is False
    assert users.authenticate(conn, "ferran", "vieja")   # la clave no cambió


def test_recuperar_sin_pregunta_no_permite(conn):
    users.create_user(conn, "ferran", "vieja")           # sin pregunta de recuperación
    assert users.get_recovery_question(conn, "ferran") is None
    assert users.reset_password(conn, "ferran", "loquesea", "nueva") is False


# ---- Sesiones recordadas ----
def test_sesion_recordada(conn):
    uid = users.create_user(conn, "ferran", "clave")
    token = users.create_session(conn, uid)
    assert token
    assert users.validate_session(conn, token) == uid
    users.delete_session(conn, token)
    assert users.validate_session(conn, token) is None


def test_sesion_token_invalido(conn):
    assert users.validate_session(conn, "no-existe") is None
    assert users.validate_session(conn, "") is None


def test_sesion_caducada(conn):
    import datetime as dt
    uid = users.create_user(conn, "ferran", "clave")
    token = users.create_session(conn, uid)
    # forzamos caducidad en el pasado
    conn.execute("UPDATE sessions SET expires_at=? WHERE user_id=?",
                 ((dt.datetime.now() - dt.timedelta(days=1)).isoformat(), uid))
    conn.commit()
    assert users.validate_session(conn, token) is None
