"""Bloque 4 — Login oficial (Azure B2C).

Dos formas de iniciar sesión:

  A) Email + contraseña (flujo ROPC, política B2C_1A_ResourceOwnerv2).
  B) Con Google u otra red social: flujo interactivo Authorization Code + PKCE
     (política B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN), que es el único que admite
     cuentas de Google. El usuario abre la página oficial de LaLiga, entra con
     Google y pega de vuelta la dirección final (authredirect://...?code=...).
     Este flujo devuelve refresh_token → la sesión se renueva sola durante días.

SEGURIDAD:
  - La contraseña (si se usa) va SOLO al endpoint oficial de LaLiga por HTTPS.
  - No se guarda contraseña; solo tokens, en memoria de sesión.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass

import requests

CLIENT_ID = "af88bcff-1157-40a0-b579-030728aacf0b"
_BASE = "https://login.laliga.es/laligadspprob2c.onmicrosoft.com/oauth2/v2.0"
TOKEN_BASE = f"{_BASE}/token"
AUTHORIZE_BASE = f"{_BASE}/authorize"
ROPC_POLICY = "B2C_1A_ResourceOwnerv2"                 # email + contraseña
SIGNIN_POLICY = "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN"    # interactivo (Google)
REDIRECT_URI = "authredirect://com.lfp.laligafantasy"
SCOPE = f"openid {CLIENT_ID} offline_access"


class AuthError(RuntimeError):
    pass


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str | None
    expires_at: float                 # epoch seconds
    policy: str = ROPC_POLICY         # política con la que se emitió (para refrescar)

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - 60)


def _token_url(policy: str) -> str:
    return f"{TOKEN_BASE}?p={policy}"


def _post_token(data: dict, policy: str, timeout: int = 20) -> TokenBundle:
    try:
        r = requests.post(
            _token_url(policy), data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise AuthError(f"No se pudo contactar con el login de LaLiga: {exc}") from exc

    if r.status_code != 200:
        msg = ""
        try:
            msg = r.json().get("error_description", "")
        except Exception:
            msg = r.text[:200]
        primera = msg.splitlines()[0] if msg else ""
        raise AuthError(f"Login rechazado (HTTP {r.status_code}). {primera}")

    return _parse_token(r.json(), policy)


def _parse_token(payload: dict, policy: str = ROPC_POLICY) -> TokenBundle:
    access = payload.get("access_token") or payload.get("id_token")
    if not access:
        raise AuthError("La respuesta de login no contiene token de acceso.")
    return TokenBundle(
        access_token=access,
        refresh_token=payload.get("refresh_token"),
        expires_at=time.time() + int(payload.get("expires_in", 3600)),
        policy=policy,
    )


# ---- A) Email + contraseña ----------------------------------------------
def login(email: str, password: str) -> TokenBundle:
    if not email or not password:
        raise AuthError("Introduce email y contraseña.")
    return _post_token({
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "scope": SCOPE,
        "redirect_uri": REDIRECT_URI,
        "username": email,
        "password": password,
        "response_type": "token id_token",
    }, ROPC_POLICY)


def refresh(refresh_token: str, policy: str = ROPC_POLICY) -> TokenBundle:
    if not refresh_token:
        raise AuthError("No hay refresh_token disponible; vuelve a iniciar sesión.")
    return _post_token({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "scope": SCOPE,
        "refresh_token": refresh_token,
    }, policy)


# ---- B) Google (Authorization Code + PKCE) ------------------------------
def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def make_pkce() -> tuple[str, str]:
    """Devuelve (code_verifier, code_challenge S256)."""
    verifier = _b64url(os.urandom(40))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def make_state() -> str:
    return secrets.token_urlsafe(16)


def build_authorize_url(code_challenge: str, state: str, nonce: str) -> str:
    """URL de la página oficial de login (con opción de Google)."""
    params = {
        "p": SIGNIN_POLICY,
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_BASE}?{urllib.parse.urlencode(params)}"


def extract_code(redirect_url_or_code: str) -> str:
    """Extrae el `code` de la dirección pegada (authredirect://...?code=...),
    o acepta el código pelado si el usuario pega solo eso."""
    s = (redirect_url_or_code or "").strip()
    if not s:
        raise AuthError("Pega la dirección que empieza por authredirect:// o el código.")
    if "code=" in s:
        query = urllib.parse.urlparse(s).query or s.split("?", 1)[-1]
        params = urllib.parse.parse_qs(query)
        code = (params.get("code") or [""])[0]
        if not code:
            raise AuthError("No se encontró 'code' en la dirección pegada.")
        return code
    return s  # se asume que es el código directamente


def exchange_code(code: str, code_verifier: str) -> TokenBundle:
    """Canjea el `code` por tokens (incluye refresh_token)."""
    if not code or not code_verifier:
        raise AuthError("Falta el código o el verificador PKCE.")
    return _post_token({
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
        "scope": SCOPE,
    }, SIGNIN_POLICY)
