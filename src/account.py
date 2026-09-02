"""Bloque 4 — Cliente autenticado de la cuenta oficial.

Con el token del login (auth.py) obtiene los datos PERSONALES:
  - tus ligas (con tu teamId, tu dinero y tus puntos en cada una)
  - tu plantilla (ids de jugador que ya tienes)
  - tu dinero disponible
  - el mercado actual de tu liga (jugadores a los que puedes pujar esta jornada)

Endpoints verificados en el código de apps que usan la misma API. Los tokens
solo viven en memoria/sesión; nunca se persisten aquí.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

from .api_client import BASE_URL, COMPETITION_ID, LANG

_HEADERS = {"User-Agent": "Mozilla/5.0 (liga-fantasy-predictor)", "Accept": "application/json"}


class AccountError(RuntimeError):
    pass


@dataclass
class MyLeague:
    id: str
    name: str
    team_id: int
    money: int
    team_points: int
    managers: int


@dataclass
class MarketEntry:
    player_id: int
    nickname: str
    position_id: int
    market_value: int
    sale_price: int          # precio de salida / cláusula de venta
    expiration: str
    num_bids: int
    is_direct_sale: bool     # True si lo vende un mánager (no la máquina)


@dataclass
class MyTeam:
    team_id: int
    money: int
    team_value: int
    player_ids: list[int] = field(default_factory=list)  # playerMaster ids


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class AccountClient:
    """Cliente con token Bearer. `token_provider` devuelve un access_token válido
    (permite refresco transparente si se pasa una función)."""

    def __init__(self, token: str | None = None, token_provider=None,
                 base_url: str = BASE_URL, competition_id: int = COMPETITION_ID,
                 lang: str = LANG, timeout: int = 20):
        if not token and not token_provider:
            raise AccountError("Se requiere un token o un token_provider.")
        self._static_token = token
        self._token_provider = token_provider
        self.base_url = base_url.rstrip("/")
        self.cmp = f"/v1/competition/{competition_id}"
        self.lang = lang
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _token(self) -> str:
        return self._token_provider() if self._token_provider else self._static_token

    def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self._token()}"}
        try:
            r = self._session.get(url, params={"x-lang": self.lang},
                                  headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise AccountError(f"Fallo de red en {path}: {exc}") from exc
        if r.status_code in (401, 403):
            raise AccountError("Sesión no válida o caducada. Vuelve a iniciar sesión.")
        if r.status_code != 200:
            raise AccountError(f"GET {path} -> HTTP {r.status_code}: {r.text[:150]}")
        return r.json()

    # ---- Datos personales ----------------------------------------------
    def get_me(self) -> dict:
        return self._get("/v4/user/me")

    def get_leagues(self) -> list[MyLeague]:
        raw = self._get(f"{self.cmp}/leagues")
        # La API 26/27 envuelve la lista; aceptamos lista directa o {'leagues': [...]}
        items = raw.get("leagues", raw) if isinstance(raw, dict) else raw
        leagues: list[MyLeague] = []
        for lg in items:
            team = lg.get("team", {}) or {}
            leagues.append(MyLeague(
                id=str(lg.get("id", "")),
                name=lg.get("name", ""),
                team_id=_to_int(team.get("id")),
                money=_to_int(team.get("money")),
                team_points=_to_int(team.get("teamPoints")),
                managers=_to_int(lg.get("managersNumber")),
            ))
        return leagues

    def get_money(self, team_id: int) -> int:
        raw = self._get(f"{self.cmp}/teams/{team_id}/money")
        return _to_int(raw.get("teamMoney"))

    def get_team(self, league_id: str, team_id: int) -> MyTeam:
        raw = self._get(f"{self.cmp}/leagues/{league_id}/teams/{team_id}")
        players = raw.get("players", []) or []
        ids = [_to_int((p.get("playerMaster") or {}).get("id")) for p in players]
        ids = [i for i in ids if i]
        return MyTeam(
            team_id=team_id,
            money=_to_int(raw.get("teamMoney")),
            team_value=_to_int(raw.get("teamValue")),
            player_ids=ids,
        )

    def get_market(self, league_id: str) -> list[MarketEntry]:
        raw = self._get(f"{self.cmp}/league/{league_id}/market")
        items = raw.get("market", raw) if isinstance(raw, dict) else raw
        market: list[MarketEntry] = []
        for m in items:
            pm = m.get("playerMaster", {}) or {}
            market.append(MarketEntry(
                player_id=_to_int(pm.get("id")),
                nickname=pm.get("nickname", ""),
                position_id=_to_int(pm.get("positionId")),
                market_value=_to_int(pm.get("marketValue")),
                sale_price=_to_int(m.get("salePrice")),
                expiration=str(m.get("expirationDate", "")),
                num_bids=_to_int(m.get("numberOfBids")),
                is_direct_sale=bool(m.get("sellerTeam")),
            ))
        return market
