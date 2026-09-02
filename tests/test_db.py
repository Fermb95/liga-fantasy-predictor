"""Tests de la capa SQLite: esquema, upserts idempotentes y datos por jornada."""
import pytest

from src import db
from src.api_client import Fixture, Player, Team


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.init_db(c)
    yield c
    c.close()


def _player(pid=1, mv=1000000, wp=None):
    return Player(
        id=pid, nickname=f"Jugador{pid}", position_id=3, team_id=15,
        market_value=mv, points=50, average_points=5.0, last_season_points=100,
        status="ok", image="", week_points=wp or {1: 8, 2: 6},
    )


def test_upsert_teams_y_players(conn):
    db.upsert_teams(conn, [Team(15, "Real Madrid", "badge.png")])
    n = db.upsert_players(conn, [_player()])
    assert n == 1
    row = conn.execute("SELECT nickname, market_value FROM players WHERE id=1").fetchone()
    assert row["nickname"] == "Jugador1"
    assert row["market_value"] == 1000000


def test_upsert_es_idempotente_y_actualiza(conn):
    db.upsert_teams(conn, [Team(15, "Real Madrid", "b")])
    db.upsert_players(conn, [_player(mv=1000000)])
    db.upsert_players(conn, [_player(mv=1250000)])  # mismo id, nuevo valor
    rows = conn.execute("SELECT COUNT(*) c FROM players").fetchone()
    assert rows["c"] == 1  # no duplica
    val = conn.execute("SELECT market_value FROM players WHERE id=1").fetchone()["market_value"]
    assert val == 1250000  # actualiza


def test_week_points_se_guardan(conn):
    db.upsert_teams(conn, [Team(15, "Real Madrid", "b")])
    db.upsert_players(conn, [_player(wp={1: 8, 2: 6, 3: 12})])
    n = conn.execute("SELECT COUNT(*) c FROM player_week_points WHERE player_id=1").fetchone()["c"]
    assert n == 3
    p3 = conn.execute("SELECT points FROM player_week_points WHERE player_id=1 AND week=3").fetchone()
    assert p3["points"] == 12


def test_upsert_fixtures(conn):
    fx = [Fixture(match_id=100, week=1, date="2026-08-15", local_id=15, visitor_id=4,
                  local_score=2, visitor_score=1, match_state=7)]
    n = db.upsert_fixtures(conn, fx)
    assert n == 1
    row = conn.execute("SELECT local_id, visitor_id FROM fixtures WHERE match_id=100").fetchone()
    assert row["local_id"] == 15 and row["visitor_id"] == 4


def test_meta_roundtrip(conn):
    db.set_meta(conn, "last_ingest", "2026-09-02T10:00:00")
    assert db.get_meta(conn, "last_ingest") == "2026-09-02T10:00:00"
    assert db.get_meta(conn, "no_existe") is None
