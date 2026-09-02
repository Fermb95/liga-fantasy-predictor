"""Cliente de la API pública de LaLiga Fantasy Oficial (Relevo).

Solo endpoints públicos (sin login): jugadores, calendario/partidos y equipos.
El login OAuth de la cuenta personal se añadirá en un bloque posterior.

Endpoints verificados en vivo (temporada del juego, competition=1):
  - GET /api/v1/competition/1/players            -> lista de jugadores
  - GET /stats/v1/competition/1/stats/week/{n}   -> partidos de la jornada n
Los equipos se derivan de los partidos (no hay endpoint público de equipos).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests

BASE_URL = "https://fantasy-api.llt-services.com"
COMPETITION_ID = 1
LANG = "es"

# Mapas de referencia (positionId / playerStatus) según la API.
POSITIONS = {1: "Portero", 2: "Defensa", 3: "Centrocampista", 4: "Delantero", 5: "Entrenador"}
STATUSES = {
    "ok": "Disponible",
    "injured": "Lesionado",
    "suspended": "Sancionado",
    "doubtful": "Duda",
    "out_of_league": "Fuera de la liga",
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (liga-fantasy-predictor)",
    "Accept": "application/json",
}


@dataclass
class Player:
    id: int
    nickname: str
    position_id: int
    team_id: int
    market_value: int
    points: int
    average_points: float
    last_season_points: int
    status: str
    image: str
    week_points: dict[int, int] = field(default_factory=dict)  # {jornada: puntos}

    @property
    def position(self) -> str:
        return POSITIONS.get(self.position_id, "Desconocido")

    @property
    def status_es(self) -> str:
        return STATUSES.get(self.status, self.status)


@dataclass
class Team:
    id: int
    name: str
    badge: str


@dataclass
class Fixture:
    match_id: int
    week: int
    date: str
    local_id: int
    visitor_id: int
    local_score: int | None
    visitor_score: int | None
    match_state: int


class FantasyAPIError(RuntimeError):
    pass


class FantasyClient:
    """Cliente HTTP con reintentos ante errores transitorios (5xx)."""

    def __init__(self, base_url: str = BASE_URL, competition_id: int = COMPETITION_ID,
                 lang: str = LANG, timeout: int = 20, max_retries: int = 4):
        self.base_url = base_url.rstrip("/")
        self.competition_id = competition_id
        self.lang = lang
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        params = {"x-lang": self.lang}
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = self._session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:  # red caída / timeout
                last_exc = exc
            else:
                if r.status_code == 200:
                    return r.json()
                # 5xx suele ser transitorio en esta API; reintentamos.
                if r.status_code < 500:
                    raise FantasyAPIError(f"GET {path} -> HTTP {r.status_code}: {r.text[:200]}")
                last_exc = FantasyAPIError(f"GET {path} -> HTTP {r.status_code}")
            time.sleep(0.8 * (attempt + 1))
        raise FantasyAPIError(f"GET {path} falló tras {self.max_retries} intentos: {last_exc}")

    # ---- Jugadores -------------------------------------------------------
    def get_players(self) -> list[Player]:
        raw = self._get(f"/api/v1/competition/{self.competition_id}/players")
        return [self._parse_player(p) for p in raw]

    @staticmethod
    def _parse_player(p: dict) -> Player:
        wp = {int(w["weekNumber"]): int(w["points"]) for w in p.get("weekPoints", [])}
        return Player(
            id=int(p["id"]),
            nickname=p.get("nickname", ""),
            position_id=int(p["positionId"]),
            team_id=int(p["teamId"]),
            market_value=int(p.get("marketValue") or 0),
            points=int(p.get("points") or 0),
            average_points=float(p.get("averagePoints") or 0),
            last_season_points=int(p.get("lastSeasonPoints") or 0),
            status=p.get("playerStatus", "ok"),
            image=p.get("image", ""),
            week_points=wp,
        )

    # ---- Partidos / calendario ------------------------------------------
    def get_week_stats(self, week: int) -> list[Fixture]:
        raw = self._get(f"/stats/v1/competition/{self.competition_id}/stats/week/{week}")
        return [self._parse_fixture(m, week) for m in raw]

    @staticmethod
    def _parse_fixture(m: dict, week: int) -> Fixture:
        return Fixture(
            match_id=int(m["id"]),
            week=week,
            date=m.get("date", ""),
            local_id=int(m["local"]["id"]),
            visitor_id=int(m["visitor"]["id"]),
            local_score=m.get("localScore"),
            visitor_score=m.get("visitorScore"),
            match_state=int(m.get("matchState") or 0),
        )

    def get_teams_from_week(self, week: int = 1) -> list[Team]:
        """Deriva los equipos (id, nombre, escudo) de los partidos de una jornada."""
        raw = self._get(f"/stats/v1/competition/{self.competition_id}/stats/week/{week}")
        teams: dict[int, Team] = {}
        for m in raw:
            for side in ("local", "visitor"):
                t = m[side]
                tid = int(t["id"])
                teams[tid] = Team(id=tid, name=t.get("mainName", ""), badge=t.get("badgeColor", ""))
        return sorted(teams.values(), key=lambda x: x.id)

    def get_all_fixtures(self, first: int = 1, last: int = 38) -> list[Fixture]:
        """Recorre las jornadas y acumula los partidos que la API devuelva."""
        fixtures: list[Fixture] = []
        for week in range(first, last + 1):
            try:
                wk = self.get_week_stats(week)
            except FantasyAPIError:
                continue  # jornada aún no publicada
            if not wk:
                continue
            fixtures.extend(wk)
        return fixtures
