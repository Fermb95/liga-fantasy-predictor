"""Capa de datos: SQLite en local, Turso (libSQL) en la nube.

Mismo esquema y mismo SQL para ambos backends (Turso es SQLite compatible). Si
existen las credenciales de Turso (env TURSO_DATABASE_URL + TURSO_AUTH_TOKEN, que
la app copia desde los secrets de Streamlit), se usa Turso —persistente y
compartido entre usuarios—; si no, un fichero SQLite local (desarrollo).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .api_client import Fixture, Player, Team

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "fantasy.db"


def _turso_creds() -> tuple[str | None, str | None]:
    return os.environ.get("TURSO_DATABASE_URL"), os.environ.get("TURSO_AUTH_TOKEN")


def using_turso() -> bool:
    url, token = _turso_creds()
    return bool(url and token)


# Cliente Turso compartido y esquema aplicado una sola vez (rendimiento: evita
# recrear el cliente HTTP y reaplicar el esquema en cada db.connect()).
_turso_client = None
_turso_schema_done = False


def _get_turso_client(url: str, token: str):
    global _turso_client
    if _turso_client is None:
        import libsql_client
        u = url.replace("libsql://", "https://") if url.startswith("libsql://") else url
        _turso_client = libsql_client.create_client_sync(url=u, auth_token=token)
    return _turso_client


# ---- Adaptador Turso: expone la misma interfaz que sqlite3.Connection --------
class _TursoCursor:
    """Cursor sobre un ResultSet de libsql_client; devuelve filas como dict."""
    def __init__(self, result_set):
        self._rows = [dict(r.asdict()) for r in result_set.rows]
        self._i = 0
        self.lastrowid = getattr(result_set, "last_insert_rowid", None)

    def fetchone(self):
        if self._i < len(self._rows):
            row = self._rows[self._i]
            self._i += 1
            return row
        return None

    def fetchall(self):
        rows = self._rows[self._i:]
        self._i = len(self._rows)
        return rows

    def __iter__(self):
        return iter(self._rows)


class _TursoConnection:
    """Conexión a Turso con la interfaz mínima de sqlite3 que usa la app."""
    def __init__(self, url: str, token: str, client=None, libsql=None):
        global _turso_schema_done
        if libsql is None:
            import libsql_client as libsql
        self._libsql = libsql
        self._c = client if client is not None else _get_turso_client(url, token)
        # El esquema/migración se aplican una única vez por proceso, no en cada
        # conexión (con Turso cada sentencia es una llamada de red).
        if not _turso_schema_done:
            self.executescript(SCHEMA)
            _migrate(self)
            _turso_schema_done = True

    def execute(self, sql, params=()):
        rs = self._c.execute(sql, list(params)) if params else self._c.execute(sql)
        return _TursoCursor(rs)

    def executemany(self, sql, seq):
        stmts = [self._libsql.Statement(sql, list(p)) for p in seq]
        if stmts:
            self._c.batch(stmts)

    def executescript(self, script):
        stmts = [s.strip() for s in script.split(";") if s.strip()]
        if stmts:
            self._c.batch([self._libsql.Statement(s) for s in stmts])

    def commit(self):
        pass  # libsql_client hace autocommit por sentencia

    def close(self):
        pass  # cliente compartido y cacheado: no se cierra en cada uso

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

-- Momento de la última actualización de datos (global, compartido).
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Histórico del valor de mercado (un snapshot por jugador y fecha de ingesta).
CREATE TABLE IF NOT EXISTS value_history (
    player_id    INTEGER NOT NULL,
    date         TEXT NOT NULL,
    market_value INTEGER NOT NULL,
    PRIMARY KEY (player_id, date)
);

-- Cuentas de usuario (contraseña cifrada con PBKDF2 + salt).
CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    username             TEXT UNIQUE NOT NULL,
    password_hash        TEXT NOT NULL,
    salt                 TEXT NOT NULL,
    created_at           TEXT,
    recovery_question    TEXT,
    recovery_answer_hash TEXT
);

-- Sesiones recordadas (token en el navegador → login automático).
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER,
    expires_at TEXT
);

-- Dinero "para gastar" de cada usuario.
CREATE TABLE IF NOT EXISTS budgets (
    user_id INTEGER PRIMARY KEY,
    amount  INTEGER NOT NULL DEFAULT 0
);

-- Plantilla de cada usuario.
CREATE TABLE IF NOT EXISTS roster (
    user_id        INTEGER NOT NULL,
    player_id      INTEGER NOT NULL,
    purchase_price INTEGER,
    clause         INTEGER,
    added_at       TEXT,
    PRIMARY KEY (user_id, player_id)
);

-- Historial de compras y ventas por usuario.
CREATE TABLE IF NOT EXISTS transactions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER,
    player_id INTEGER,
    kind      TEXT,     -- 'buy' | 'sell'
    price     INTEGER,
    ts        TEXT
);

-- Pujas en curso por usuario (dinero retenido).
CREATE TABLE IF NOT EXISTS bids (
    user_id   INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    amount    INTEGER,
    ts        TEXT,
    PRIMARY KEY (user_id, player_id)
);

-- Jugadores en venta por usuario.
CREATE TABLE IF NOT EXISTS listings (
    user_id   INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    ask_price INTEGER,
    ts        TEXT,
    PRIMARY KEY (user_id, player_id)
);

-- "Mi mercado": jugadores que le salen a cada usuario ahora mismo (rotan).
CREATE TABLE IF NOT EXISTS user_market (
    user_id   INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    ts        TEXT,
    PRIMARY KEY (user_id, player_id)
);
"""


def connect(db_path: str | Path = DEFAULT_DB):
    """Devuelve una conexión: Turso si hay credenciales, si no SQLite local."""
    url, token = _turso_creds()
    if url and token:
        return _TursoConnection(url, token)

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Asegura el esquema en cada conexión (idempotente). Evita errores de
    # "no such table" en un despliegue nuevo con la BD aún vacía.
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn


def _migrate(conn) -> None:
    """Migraciones idempotentes para BDs creadas antes de nuevas columnas."""
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    except Exception:
        return
    for col in ("recovery_question", "recovery_answer_hash"):
        if col not in cols:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
                conn.commit()
            except Exception:
                pass


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)


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


# ---- Histórico de valor de mercado --------------------------------------
def record_values(conn: sqlite3.Connection, players: list[Player], date: str | None = None) -> int:
    """Guarda un snapshot del valor de mercado de cada jugador para la fecha dada
    (por defecto hoy). Idempotente por (player_id, date)."""
    import datetime as _dt
    date = date or _dt.date.today().isoformat()
    conn.executemany(
        """INSERT INTO value_history (player_id, date, market_value) VALUES (?, ?, ?)
           ON CONFLICT(player_id, date) DO UPDATE SET market_value=excluded.market_value""",
        [(p.id, date, p.market_value) for p in players],
    )
    conn.commit()
    return len(players)


def value_history_two_latest(conn: sqlite3.Connection) -> tuple[dict[int, int], dict[int, int]]:
    """Devuelve (valores_de_la_fecha_más_reciente, valores_de_la_anterior)."""
    dates = [r["date"] for r in conn.execute(
        "SELECT DISTINCT date FROM value_history ORDER BY date DESC LIMIT 2")]
    if not dates:
        return {}, {}
    latest = {r["player_id"]: r["market_value"] for r in conn.execute(
        "SELECT player_id, market_value FROM value_history WHERE date=?", (dates[0],))}
    prev = {}
    if len(dates) > 1:
        prev = {r["player_id"]: r["market_value"] for r in conn.execute(
            "SELECT player_id, market_value FROM value_history WHERE date=?", (dates[1],))}
    return latest, prev


def get_value_history(conn: sqlite3.Connection, player_id: int) -> list[tuple[str, int]]:
    return [(r["date"], r["market_value"]) for r in conn.execute(
        "SELECT date, market_value FROM value_history WHERE player_id=? ORDER BY date", (player_id,))]
