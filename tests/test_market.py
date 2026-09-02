"""Tests de precios recomendados y simulador de fichajes (Bloque 8)."""
from src import market
from src.api_client import Player
from src.engine import PlayerScore


def ps(pid, score, mv, pos=4):
    p = Player(id=pid, nickname=f"J{pid}", position_id=pos, team_id=1, market_value=mv,
               points=score, average_points=5, last_season_points=0, status="ok",
               image="", week_points={1: 5})
    return PlayerScore(player=p, score=score, signal="", rentabilidad=1.0,
                       forma=5.0, titularidad=1.0, facilidad_calendario=0.5)


def test_price_advice_mejor_jugador_mas_sobreprecio_y_clausula():
    bueno = market.price_advice(ps(1, 100, 10_000_000))
    malo = market.price_advice(ps(2, 20, 10_000_000))
    assert bueno.fair_value == 10_000_000
    assert bueno.max_buy > malo.max_buy               # pagas más por el mejor
    assert bueno.suggested_clause > malo.suggested_clause
    assert bueno.max_buy >= bueno.fair_value          # nunca por debajo del valor


def test_financing_te_llega_sin_vender():
    target = ps(1, 80, 5_000_000)
    plan = market.financing_plan(target, budget=10_000_000, squad=[])
    assert plan.affordable_now
    assert plan.sells == []
    assert plan.budget_after == 10_000_000 - plan.price


def test_financing_necesita_vender():
    target = ps(1, 90, 100_000_000, pos=4)         # Mbappé caro
    # Plantilla con jugadores de distinto valor/score.
    squad = [ps(10, 30, 20_000_000), ps(11, 70, 40_000_000), ps(12, 20, 50_000_000)]
    plan = market.financing_plan(target, budget=10_000_000, squad=squad)
    assert not plan.affordable_now
    assert plan.shortfall > 0
    assert plan.sells, "debe proponer ventas"
    # Vende primero los de menor score (12 score20, 10 score30) antes que el 11.
    vendidos = [s.player.id for s in plan.sells]
    assert vendidos[0] in (12, 10)
    assert 11 not in vendidos or vendidos.index(11) == len(vendidos) - 1


def test_financing_no_factible():
    target = ps(1, 90, 200_000_000)
    squad = [ps(10, 30, 1_000_000)]
    plan = market.financing_plan(target, budget=1_000_000, squad=squad)
    assert not plan.feasible


def test_financing_sacrifica_lo_menos_valioso_primero():
    target = ps(1, 90, 25_000_000)          # precio ~29,6M
    # Con 5M + dos flojos (15M c/u = 30M) se llega sin tocar al crack.
    squad = [ps(10, 10, 15_000_000), ps(11, 95, 15_000_000), ps(12, 12, 15_000_000)]
    plan = market.financing_plan(target, budget=5_000_000, squad=squad)
    vendidos = [s.player.id for s in plan.sells]
    assert plan.feasible
    assert 11 not in vendidos               # no vende al crack; le bastan los flojos
