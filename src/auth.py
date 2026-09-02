"""Bloque 4 — Login oficial (Azure B2C, flujo ROPC).

Autentica contra el tenant B2C de LaLiga con email + contraseña y obtiene un
`access_token` (Bearer) y un `refresh_token` (gracias a `offline_access`) para
renovar sin volver a pedir la contraseña.

SEGURIDAD:
  - La contraseña se envía SOLO al endpoint oficial de LaLiga por HTTPS.
  - Nunca se guarda en disco ni se registra en logs; solo se conservan tokens.
  - Cuentas creadas con "login con Google" NO admiten este flujo: para esas,
    usar el pegado manual de token (ver app / README).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

CLIENT_ID = "af88bcff-1157-40a0-b579-030728aacf0b"
TOKEN_URL = ("https://login.laliga.es/laligadspprob2c.onmicrosoft.com/"
             "oauth2/v2.0/token?p=B2C_1A_ResourceOwnerv2")
REDIRECT_URI = "authredirect://com.lfp.laligafantasy"
SCOPE = f"openid {CLIENT_ID} offline_access"


class AuthError(RuntimeError):
    pass


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str | None
    expires_at: float  # epoch seconds

    @property
    def is_expired(self) -> bool:
        # Margen de 60 s para no apurar.
        return time.time() >= (self.expires_at - 60)


def _post_token(data: dict, timeout: int = 20) -> TokenBundle:
    try:
        r = requests.post(
            TOKEN_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise AuthError(f"No se pudo contactar con el login de LaLiga: {exc}") from exc

    if r.status_code != 200:
        # B2C devuelve JSON con error_description en los fallos.
        msg = ""
        try:
            msg = r.json().get("error_description", "")
        except Exception:
            msg = r.text[:200]
        raise AuthError(f"Login rechazado (HTTP {r.status_code}). {msg.splitlines()[0] if msg else ''}")

    return _parse_token(r.json())


def _parse_token(payload: dict) -> TokenBundle:
    access = payload.get("access_token") or payload.get("id_token")
    if not access:
        raise AuthError("La respuesta de login no contiene token de acceso.")
    expires_in = int(payload.get("expires_in", 3600))
    return TokenBundle(
        access_token=access,
        refresh_token=payload.get("refresh_token"),
        expires_at=time.time() + expires_in,
    )


def login(email: str, password: str) -> TokenBundle:
    """Inicia sesión con email + contraseña y devuelve los tokens."""
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
    })


def refresh(refresh_token: str) -> TokenBundle:
    """Renueva el token de acceso usando el refresh_token."""
    if not refresh_token:
        raise AuthError("No hay refresh_token disponible; vuelve a iniciar sesión.")
    return _post_token({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "scope": SCOPE,
        "refresh_token": refresh_token,
        "response_type": "token id_token",
    })
