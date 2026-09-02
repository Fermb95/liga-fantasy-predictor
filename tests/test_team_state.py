"""Tests del estado del equipo (Bloque 6): plantilla, presupuesto y compra/venta."""
import pytest

from src import db, team_state as ts


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def test_presupuesto_roundtrip(conn):
    assert ts.get_budget(conn) == 0
    ts.set_budget(conn, 5_000_000)
    assert ts.get_budget(conn) == 5_000_000
    ts.set_budget(conn, -100)          # no permite negativos
    assert ts.get_budget(conn) == 0


def test_set_roster_inicial(conn):
    ts.set_roster(conn, [10, 20, 30], prices={10: 4_000_000})
    ids = ts.get_roster_ids(conn)
    assert ids == {10, 20, 30}
    entries = {e.player_id: e for e in ts.get_roster(conn)}
    assert entries[10].purchase_price == 4_000_000
    assert entries[20].purchase_price is None


def test_set_roster_reemplaza(conn):
    ts.set_roster(conn, [1, 2])
    ts.set_roster(conn, [3])
    assert ts.get_roster_ids(conn) == {3}


def test_comprar_actualiza_plantilla_y_dinero(conn):
    ts.set_budget(conn, 10_000_000)
    restante = ts.buy_player(conn, 99, 6_000_000, clause=8_000_000)
    assert restante == 4_000_000
    assert 99 in ts.get_roster_ids(conn)
    e = {x.player_id: x for x in ts.get_roster(conn)}[99]
    assert e.purchase_price == 6_000_000 and e.clause == 8_000_000


def test_vender_actualiza_plantilla_y_dinero(conn):
    ts.set_budget(conn, 1_000_000)
    ts.buy_player(conn, 99, 0)              # tenerlo en plantilla
    restante = ts.sell_player(conn, 99, 7_500_000)
    assert restante == 8_500_000
    assert 99 not in ts.get_roster_ids(conn)


def test_historial_registra_operaciones(conn):
    ts.set_budget(conn, 20_000_000)
    ts.buy_player(conn, 1, 5_000_000)
    ts.sell_player(conn, 1, 6_000_000)
    hist = ts.get_transactions(conn)
    assert [h["kind"] for h in hist] == ["sell", "buy"]   # más reciente primero
    assert hist[0]["price"] == 6_000_000


def test_set_clause(conn):
    ts.buy_player(conn, 5, 1_000_000)
    ts.set_clause(conn, 5, 12_000_000)
    e = {x.player_id: x for x in ts.get_roster(conn)}[5]
    assert e.clause == 12_000_000
