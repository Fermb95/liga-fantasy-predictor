"""Tests del comparador y simulador de pujas múltiples (Bloque 12)."""
from src import compare
from src.api_client import Player
from src.engine import PlayerScore


def ps(pid, score, mv, pos=3, signal="MANTENER"):
    p = Player(id=pid, nickname=f"J{pid}", position_id=pos, team_id=1, market_value=mv,
               points=score, average_points=5, last_season_points=0, status="ok",
               image="", week_points={1: 5})
    return PlayerScore(player=p, score=score, signal=signal, rentabilidad=1.0,
                       forma=5.0, titularidad=1.0, facilidad_calendario=0.5)


def test_multi_te_llega_sin_vender():
    t = [(ps(1, 80, 5_000_000, pos=4), 5_000_000),
         (ps(2, 75, 3_000_000, pos=2), 3_000_000)]
    plan = compare.multi_bid_plan(t, disponible=20_000_000, squad=[])
    assert plan.total_cost == 8_000_000
    assert plan.affordable and plan.feasible
    assert plan.cash_after == 12_000_000
    assert plan.sells == []


def test_multi_necesita_vender():
    t = [(ps(1, 90, 40_000_000, pos=4), 40_000_000),
         (ps(2, 85, 30_000_000, pos=2), 30_000_000)]
    squad = [ps(10, 20, 25_000_000, pos=3), ps(11, 80, 25_000_000, pos=3),
             ps(12, 15, 25_000_000, pos=3)]
    plan = compare.multi_bid_plan(t, disponible=10_000_000, squad=squad)
    assert not plan.affordable
    assert plan.shortfall == 60_000_000
    assert plan.sells, "debe proponer ventas"
    # Vende primero los de menor score (12 y 10) antes que el crack (11).
    ids = [s.player.id for s in plan.sells]
    assert ids[0] in (10, 12)


def test_multi_marca_no_merece_la_pena():
    # Un objetivo con señal VENDER (no rinde) -> worth=False y aviso.
    t = [(ps(1, 20, 5_000_000, pos=4, signal="VENDER"), 5_000_000)]
    plan = compare.multi_bid_plan(t, disponible=10_000_000, squad=[])
    assert plan.targets[0].worth is False
    assert any("pasar" in n for n in plan.notes)


def test_multi_detecta_overbid():
    target = ps(1, 50, 10_000_000, pos=4)     # max_buy ~ 12.5M
    t = [(target, 20_000_000)]                 # pujas muy por encima
    plan = compare.multi_bid_plan(t, disponible=50_000_000, squad=[])
    assert plan.targets[0].overbid is True
    assert any("máximo" in n for n in plan.notes)


def test_multi_aviso_misma_posicion():
    t = [(ps(1, 80, 5_000_000, pos=4), 5_000_000),
         (ps(2, 78, 5_000_000, pos=4), 5_000_000)]
    plan = compare.multi_bid_plan(t, disponible=50_000_000, squad=[])
    assert any("delantera" in n for n in plan.notes)


def test_multi_no_factible():
    t = [(ps(1, 90, 200_000_000, pos=4), 200_000_000)]
    squad = [ps(10, 20, 1_000_000, pos=3)]
    plan = compare.multi_bid_plan(t, disponible=1_000_000, squad=squad)
    assert not plan.feasible
    assert any("No te llega" in n for n in plan.notes)


def test_best_of():
    assert compare.best_of([ps(1, 50, 1), ps(2, 90, 1), ps(3, 70, 1)]).player.id == 2
    assert compare.best_of([]) is None
