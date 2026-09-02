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


# ---- Flujo Google (Authorization Code + PKCE) -------------------------------
def test_make_pkce_verifier_y_challenge():
    v, c = auth.make_pkce()
    assert v and c and v != c
    assert "=" not in c  # base64url sin padding
    v2, c2 = auth.make_pkce()
    assert v != v2  # aleatorio


def test_build_authorize_url_contiene_google_policy_y_pkce():
    url = auth.build_authorize_url("CHALLENGE", "STATE", "NONCE")
    assert auth.AUTHORIZE_BASE in url
    assert "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN" in url
    assert "code_challenge=CHALLENGE" in url
    assert "code_challenge_method=S256" in url
    assert "response_type=code" in url


def test_extract_code_desde_url_o_pelado():
    assert auth.extract_code("authredirect://com.lfp.laligafantasy?code=ABC123&state=x") == "ABC123"
    assert auth.extract_code("ABC123") == "ABC123"
    with pytest.raises(auth.AuthError):
        auth.extract_code("")


def test_exchange_code_usa_authorization_code(monkeypatch):
    capturado = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        capturado["url"] = url
        capturado["data"] = data
        return FakeResp(200, {"access_token": "A", "refresh_token": "R", "expires_in": 3600})

    monkeypatch.setattr(auth.requests, "post", fake_post)
    tb = auth.exchange_code("CODE", "VERIFIER")
    assert tb.access_token == "A" and tb.refresh_token == "R"
    assert tb.policy == auth.SIGNIN_POLICY
    assert capturado["data"]["grant_type"] == "authorization_code"
    assert capturado["data"]["code_verifier"] == "VERIFIER"
    assert "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN" in capturado["url"]


def test_refresh_respeta_politica(monkeypatch):
    capturado = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        capturado["url"] = url
        return FakeResp(200, {"access_token": "N", "expires_in": 3600})

    monkeypatch.setattr(auth.requests, "post", fake_post)
    auth.refresh("r", policy=auth.SIGNIN_POLICY)
    assert "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN" in capturado["url"]


def _fake_jwt(exp: int) -> str:
    import base64 as b64
    import json
    def part(d):
        return b64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{part({'alg':'RS256'})}.{part({'exp':exp})}.firma"


def test_token_from_pasted_quita_bearer_y_lee_exp():
    exp = int(time.time()) + 3600
    jwt = _fake_jwt(exp)
    tb = auth.token_from_pasted(f"Bearer {jwt}")
    assert tb.access_token == jwt          # se quitó 'Bearer '
    assert abs(tb.expires_at - exp) < 2     # leyó el exp real del JWT
    assert not tb.is_expired


def test_token_from_pasted_acepta_prefijo_authorization():
    jwt = _fake_jwt(int(time.time()) + 3600)
    tb = auth.token_from_pasted(f"authorization: Bearer {jwt}")
    assert tb.access_token == jwt


def test_token_from_pasted_rechaza_basura():
    with pytest.raises(auth.AuthError):
        auth.token_from_pasted("hola mundo")


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
