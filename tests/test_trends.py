"""Tests de tendencia de valor de mercado."""
import pytest

from src import db, trends
from src.api_client import Player


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def _pl(pid, mv):
    return Player(id=pid, nickname=f"J{pid}", position_id=3, team_id=1, market_value=mv,
                  points=0, average_points=0, last_season_points=0, status="ok", image="")


def test_compute_trends_sube_baja_estable():
    latest = {1: 11_000_000, 2: 9_000_000, 3: 10_000_000, 4: 5_000_000}
    prev = {1: 10_000_000, 2: 10_000_000, 3: 10_000_000}  # 4 no tenía histórico
    t = trends.compute_trends(latest, prev)
    assert t[1].direction == "up" and t[1].change == 1_000_000
    assert t[2].direction == "down" and t[2].pct == -10.0
    assert t[3].direction == "flat"
    assert t[4].direction == "new"
    assert t[1].emoji == "📈" and t[2].emoji == "📉"


def test_historico_y_tendencia_desde_bd(conn):
    db.record_values(conn, [_pl(1, 10_000_000), _pl(2, 8_000_000)], date="2026-09-01")
    db.record_values(conn, [_pl(1, 11_000_000), _pl(2, 7_500_000)], date="2026-09-02")
    t = trends.get_trends(conn)
    assert t[1].direction == "up"
    assert t[2].direction == "down"
    hist = db.get_value_history(conn, 1)
    assert hist == [("2026-09-01", 10_000_000), ("2026-09-02", 11_000_000)]


def test_snapshot_idempotente_por_dia(conn):
    db.record_values(conn, [_pl(1, 10_000_000)], date="2026-09-01")
    db.record_values(conn, [_pl(1, 10_500_000)], date="2026-09-01")  # mismo día -> actualiza
    hist = db.get_value_history(conn, 1)
    assert hist == [("2026-09-01", 10_500_000)]


def test_sin_historico(conn):
    assert trends.get_trends(conn) == {}
