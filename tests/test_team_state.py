"""Tests del estado del equipo por usuario (Bloques 6/10/15)."""
import pytest

from src import db, team_state as ts

U = 1        # usuario de prueba
U2 = 2       # otro usuario (para comprobar el aislamiento)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def test_presupuesto_roundtrip(conn):
    assert ts.get_budget(conn, U) == 0
    ts.set_budget(conn, U, 5_000_000)
    assert ts.get_budget(conn, U) == 5_000_000
    ts.set_budget(conn, U, -100)
    assert ts.get_budget(conn, U) == 0


def test_set_roster_inicial(conn):
    ts.set_roster(conn, U, [10, 20, 30], prices={10: 4_000_000})
    assert ts.get_roster_ids(conn, U) == {10, 20, 30}
    entries = {e.player_id: e for e in ts.get_roster(conn, U)}
    assert entries[10].purchase_price == 4_000_000
    assert entries[20].purchase_price is None


def test_comprar_y_vender(conn):
    ts.set_budget(conn, U, 10_000_000)
    assert ts.buy_player(conn, U, 99, 6_000_000, clause=8_000_000) == 4_000_000
    assert 99 in ts.get_roster_ids(conn, U)
    assert ts.sell_player(conn, U, 99, 7_500_000) == 11_500_000
    assert 99 not in ts.get_roster_ids(conn, U)


def test_aislamiento_entre_usuarios(conn):
    ts.set_budget(conn, U, 5_000_000)
    ts.set_roster(conn, U, [1, 2])
    ts.set_budget(conn, U2, 9_000_000)
    ts.set_roster(conn, U2, [3])
    ts.add_bid(conn, U2, 50, 1_000_000)
    # Lo de U no se ve afectado por U2 y viceversa.
    assert ts.get_roster_ids(conn, U) == {1, 2}
    assert ts.get_budget(conn, U) == 5_000_000
    assert ts.get_bids(conn, U) == {}
    assert ts.get_roster_ids(conn, U2) == {3}
    assert ts.get_bids(conn, U2) == {50: 1_000_000}


def test_pujas_y_ventas(conn):
    ts.add_bid(conn, U, 10, 3_000_000)
    ts.add_bid(conn, U, 10, 3_500_000)      # actualiza
    assert ts.get_bids(conn, U) == {10: 3_500_000}
    ts.remove_bid(conn, U, 10)
    assert ts.get_bids(conn, U) == {}
    ts.add_listing(conn, U, 20, 8_000_000)
    assert ts.get_listings(conn, U) == {20: 8_000_000}
    ts.remove_listing(conn, U, 20)
    assert ts.get_listings(conn, U) == {}


def test_historial(conn):
    ts.set_budget(conn, U, 20_000_000)
    ts.buy_player(conn, U, 1, 5_000_000)
    ts.sell_player(conn, U, 1, 6_000_000)
    hist = ts.get_transactions(conn, U)
    assert [h["kind"] for h in hist] == ["sell", "buy"]


def test_budget_view_modelo_laliga():
    bv = ts.budget_view(20_000_000, {10: 3_000_000, 11: 2_000_000}, valor_plantilla=88_000_000)
    assert bv.para_gastar == 20_000_000
    assert bv.en_pujas == 5_000_000
    assert bv.disponible == 15_000_000
    assert bv.valor_plantilla == 88_000_000


def test_export_restore_roundtrip(conn, tmp_path):
    ts.set_budget(conn, U, 7_000_000)
    ts.buy_player(conn, U, 10, 3_000_000, clause=5_000_000)   # budget -> 4M
    ts.add_bid(conn, U, 20, 2_000_000)
    ts.add_listing(conn, U, 10, 6_000_000)
    estado = ts.export_state(conn, U)

    import json
    estado2 = json.loads(json.dumps(estado))     # como pasaría por Turso/JSON
    conn2 = db.connect(tmp_path / "fresh.db")
    assert ts.is_empty(conn2, U)
    ts.restore_state(conn2, U, estado2)
    assert not ts.is_empty(conn2, U)
    assert ts.get_budget(conn2, U) == 4_000_000
    assert ts.get_roster_ids(conn2, U) == {10}
    assert ts.get_bids(conn2, U) == {20: 2_000_000}
    e = {x.player_id: x for x in ts.get_roster(conn2, U)}[10]
    assert e.purchase_price == 3_000_000 and e.clause == 5_000_000
    conn2.close()
