"""Capa SQLite: esquema + upserts. Gratis, cero configuración, un solo fichero."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .api_client import Fixture, Player, Team

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "fantasy.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    badge   TEXT
);

CREATE TABLE IF NOT EXISTS players (
    id                 INTEGER PRIMARY KEY,
    nickname           TEXT NOT NULL,
    position_id        INTEGER NOT NULL,
    team_id            INTEGER,
    market_value       INTEGER NOT NULL DEFAULT 0,
    points             INTEGER NOT NULL DEFAULT 0,
    average_points     REAL NOT NULL DEFAULT 0,
    last_season_points INTEGER NOT NULL DEFAULT 0,
    status             TEXT,
    image              TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id)
);

CREATE TABLE IF NOT EXISTS player_week_points (
    player_id  INTEGER NOT NULL,
    week       INTEGER NOT NULL,
    points     INTEGER NOT NULL,
    PRIMARY KEY (player_id, week),
    FOREIGN KEY (player_id) REFERENCES players(id)
);

CREATE TABLE IF NOT EXISTS fixtures (
    match_id      INTEGER PRIMARY KEY,
    week          INTEGER NOT NULL,
    date          TEXT,
    local_id      INTEGER,
    visitor_id    INTEGER,
    local_score   INTEGER,
    visitor_score INTEGER,
    match_state   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_fixtures_week ON fixtures(week);
CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);

-- Momento de la última actualización de datos (una fila por tabla lógica).
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Tu plantilla real (los jugadores que tienes ahora mismo).
CREATE TABLE IF NOT EXISTS roster (
    player_id      INTEGER PRIMARY KEY,
    purchase_price INTEGER,   -- lo que pagaste (o su valor al añadirlo)
    clause         INTEGER,   -- cláusula de blindaje actual
    added_at       TEXT
);

-- Historial de compras y ventas.
CREATE TABLE IF NOT EXISTS transactions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER,
    kind      TEXT,     -- 'buy' | 'sell'
    price     INTEGER,
    ts        TEXT
);

-- Pujas que tienes en curso por jugadores del mercado (dinero retenido).
CREATE TABLE IF NOT EXISTS bids (
    player_id INTEGER PRIMARY KEY,
    amount    INTEGER,
    ts        TEXT
);

-- Jugadores TUYOS que has puesto en venta, con el precio que pides.
CREATE TABLE IF NOT EXISTS listings (
    player_id INTEGER PRIMARY KEY,
    ask_price INTEGER,
    ts        TEXT
);
"""


def connect(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Asegura el esquema en cada conexión (idempotente). Evita errores de
    # "no such table" en un despliegue nuevo con la BD aún vacía.
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_teams(conn: sqlite3.Connection, teams: list[Team]) -> int:
    conn.executemany(
        """INSERT INTO teams (id, name, badge) VALUES (?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name, badge=excluded.badge""",
        [(t.id, t.name, t.badge) for t in teams],
    )
    conn.commit()
    return len(teams)


def upsert_players(conn: sqlite3.Connection, players: list[Player]) -> int:
    conn.executemany(
        """INSERT INTO players
             (id, nickname, position_id, team_id, market_value, points,
              average_points, last_season_points, status, image)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             nickname=excluded.nickname,
             position_id=excluded.position_id,
             team_id=excluded.team_id,
             market_value=excluded.market_value,
             points=excluded.points,
             average_points=excluded.average_points,
             last_season_points=excluded.last_season_points,
             status=excluded.status,
             image=excluded.image""",
        [
            (p.id, p.nickname, p.position_id, p.team_id, p.market_value, p.points,
             p.average_points, p.last_season_points, p.status, p.image)
            for p in players
        ],
    )
    # Puntos por jornada.
    rows = [(p.id, wk, pts) for p in players for wk, pts in p.week_points.items()]
    if rows:
        conn.executemany(
            """INSERT INTO player_week_points (player_id, week, points) VALUES (?, ?, ?)
               ON CONFLICT(player_id, week) DO UPDATE SET points=excluded.points""",
            rows,
        )
    conn.commit()
    return len(players)


def upsert_fixtures(conn: sqlite3.Connection, fixtures: list[Fixture]) -> int:
    conn.executemany(
        """INSERT INTO fixtures
             (match_id, week, date, local_id, visitor_id, local_score, visitor_score, match_state)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(match_id) DO UPDATE SET
             week=excluded.week, date=excluded.date,
             local_id=excluded.local_id, visitor_id=excluded.visitor_id,
             local_score=excluded.local_score, visitor_score=excluded.visitor_score,
             match_state=excluded.match_state""",
        [
            (f.match_id, f.week, f.date, f.local_id, f.visitor_id,
             f.local_score, f.visitor_score, f.match_state)
            for f in fixtures
        ],
    )
    conn.commit()
    return len(fixtures)


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


# ---- Lecturas (reconstruyen dataclasses del dominio) --------------------
def get_players(conn: sqlite3.Connection) -> list[Player]:
    prows = conn.execute("SELECT * FROM players").fetchall()
    wp: dict[int, dict[int, int]] = {}
    for r in conn.execute("SELECT player_id, week, points FROM player_week_points"):
        wp.setdefault(r["player_id"], {})[r["week"]] = r["points"]
    return [
        Player(
            id=r["id"], nickname=r["nickname"], position_id=r["position_id"],
            team_id=r["team_id"], market_value=r["market_value"], points=r["points"],
            average_points=r["average_points"], last_season_points=r["last_season_points"],
            status=r["status"], image=r["image"], week_points=wp.get(r["id"], {}),
        )
        for r in prows
    ]


def get_fixtures(conn: sqlite3.Connection) -> list[Fixture]:
    return [
        Fixture(
            match_id=r["match_id"], week=r["week"], date=r["date"],
            local_id=r["local_id"], visitor_id=r["visitor_id"],
            local_score=r["local_score"], visitor_score=r["visitor_score"],
            match_state=r["match_state"],
        )
        for r in conn.execute("SELECT * FROM fixtures")
    ]


def get_teams(conn: sqlite3.Connection) -> list[Team]:
    return [
        Team(id=r["id"], name=r["name"], badge=r["badge"])
        for r in conn.execute("SELECT * FROM teams")
    ]
