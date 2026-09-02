"""Tests del login oficial (Bloque 4). Sin credenciales reales salvo el test 'live'."""
import os
import time

import pytest

from src import auth


class FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_parse_token_calcula_expiracion():
    tb = auth._parse_token({"access_token": "abc", "refresh_token": "r", "expires_in": 3600})
    assert tb.access_token == "abc"
    assert tb.refresh_token == "r"
    assert not tb.is_expired
    assert tb.expires_at > time.time()


def test_token_expirado():
    tb = auth.TokenBundle(access_token="x", refresh_token=None, expires_at=time.time() - 10)
    assert tb.is_expired


def test_login_envia_grant_password(monkeypatch):
    capturado = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        capturado["url"] = url
        capturado["data"] = data
        return FakeResp(200, {"access_token": "TOK", "refresh_token": "REF", "expires_in": 3600})

    monkeypatch.setattr(auth.requests, "post", fake_post)
    tb = auth.login("yo@example.com", "secreto")
    assert tb.access_token == "TOK"
    assert capturado["data"]["grant_type"] == "password"
    assert capturado["data"]["username"] == "yo@example.com"
    assert "login.laliga.es" in capturado["url"]


def test_login_credenciales_vacias():
    with pytest.raises(auth.AuthError):
        auth.login("", "")


def test_login_rechazado(monkeypatch):
    def fake_post(url, data=None, headers=None, timeout=None):
        return FakeResp(400, {"error_description": "AADB2C90225: invalid credentials"})

    monkeypatch.setattr(auth.requests, "post", fake_post)
    with pytest.raises(auth.AuthError) as exc:
        auth.login("yo@example.com", "malo")
    assert "rechazado" in str(exc.value).lower()


def test_refresh_usa_grant_refresh_token(monkeypatch):
    capturado = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        capturado["data"] = data
        return FakeResp(200, {"access_token": "NUEVO", "expires_in": 3600})

    monkeypatch.setattr(auth.requests, "post", fake_post)
    tb = auth.refresh("mi-refresh")
    assert tb.access_token == "NUEVO"
    assert capturado["data"]["grant_type"] == "refresh_token"
    assert capturado["data"]["refresh_token"] == "mi-refresh"


# ---- Test real: SOLO si defines credenciales por entorno (las manejas TÚ) ----
@pytest.mark.live
def test_login_real_si_hay_credenciales():
    email = os.environ.get("LFP_EMAIL")
    password = os.environ.get("LFP_PASSWORD")
    if not email or not password:
        pytest.skip("Define LFP_EMAIL y LFP_PASSWORD para probar el login real.")
    tb = auth.login(email, password)
    assert tb.access_token
    assert not tb.is_expired
