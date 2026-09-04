"""Tests del asesor de puja/venta y encaje (Bloque 11)."""
from src import advisor
from src.api_client import Player
from src.engine import PlayerScore


def test_position_summary_niveles():
    squad = [ps(1, 90, 5_000_000, pos=1)]                       # 1 portero bueno
    squad += [ps(10 + i, 80, 5_000_000, pos=2) for i in range(4)]  # 4 defensas fuertes
    squad += [ps(20 + i, 30, 5_000_000, pos=3) for i in range(2)]  # solo 2 medios (falta fondo, need 4)
    # sin delanteros
    stats = {p.position_id: p for p in advisor.position_summary(squad)}
    assert stats[1].level == "🟢 fuerte"
    assert stats[2].level == "🟢 fuerte"
    assert stats[3].level == "🔴 falta fondo"      # 2 < 4 titulares
    assert stats[4].level == "🔴 falta fondo"      # 0 delanteros
    refuerzos = advisor.refuerzos_sugeridos(squad)
    assert 3 in refuerzos and 4 in refuerzos and 2 not in refuerzos


def ps(pid, score, mv, pos=3):
    p = Player(id=pid, nickname=f"J{pid}", position_id=pos, team_id=1, market_value=mv,
               points=score, average_points=5, last_season_points=0, status="ok",
               image="", week_points={1: 5})
    return PlayerScore(player=p, score=score, signal="", rentabilidad=1.0,
                       forma=5.0, titularidad=1.0, facilidad_calendario=0.5)


# ---- Venta ----
def test_sell_advice_minimo_es_valor_de_mercado():
    a = advisor.sell_advice(ps(1, 80, 10_000_000))
    assert a.min_accept == 10_000_000            # nunca por debajo del mercado
    assert a.good_price >= a.min_accept          # buen precio con prima


# ---- Encaje ----
def test_fit_encaja_si_falta_fondo():
    squad = [ps(1, 90, 5_000_000, pos=4)]        # solo 1 delantero
    fit, _ = advisor.team_fit(ps(2, 40, 3_000_000, pos=4), squad)
    assert fit == "ENCAJA"                        # necesitas fondo en delantera


def test_fit_mejora_si_es_mejor_que_peor_titular():
    # 4 medios titulares; el nuevo es mejor que el peor de ellos.
    squad = [ps(i, 50 + i, 5_000_000, pos=3) for i in range(4)]  # scores 50..53
    fit, _ = advisor.team_fit(ps(99, 80, 8_000_000, pos=3), squad)
    assert fit == "MEJORA"


def test_fit_no_encaja_si_ya_vas_sobrado():
    squad = [ps(i, 80 + i, 5_000_000, pos=3) for i in range(5)]  # 5 medios buenos
    fit, motivo = advisor.team_fit(ps(99, 40, 3_000_000, pos=3), squad)
    assert fit == "NO_ENCAJA"
    assert "suplente" in motivo


# ---- Puja / sustitución / financiación ----
def test_bid_plan_te_llega_sin_vender():
    target = ps(1, 90, 5_000_000, pos=4)
    squad = [ps(10, 70, 4_000_000, pos=4), ps(11, 60, 3_000_000, pos=4)]
    plan = advisor.bid_plan(target, bid=5_000_000, disponible=20_000_000, squad=squad)
    assert plan.cash_after_bid == 15_000_000
    assert plan.feasible
    # Desplaza al más flojo de su posición (id 11, score 60).
    assert plan.substitute_out.player.id == 11


def test_bid_plan_vende_al_desplazado_si_va_sobrado():
    target = ps(1, 95, 10_000_000, pos=4)
    # Ya tiene 2 delanteros (need=2) -> no encaja como fondo, desplaza al peor.
    squad = [ps(10, 80, 8_000_000, pos=4), ps(11, 70, 6_000_000, pos=4)]
    plan = advisor.bid_plan(target, bid=10_000_000, disponible=5_000_000, squad=squad)
    assert plan.substitute_out.player.id == 11
    assert plan.sell_substitute is True
    # 5M - 10M + 6M (venta del desplazado) = 1M
    assert plan.cash_if_sell_substitute == 1_000_000
    assert plan.feasible


def test_bid_plan_necesita_ventas_extra():
    target = ps(1, 95, 50_000_000, pos=4)
    squad = [ps(10, 40, 5_000_000, pos=4), ps(11, 30, 5_000_000, pos=3),
             ps(12, 20, 5_000_000, pos=3)]
    plan = advisor.bid_plan(target, bid=50_000_000, disponible=30_000_000, squad=squad)
    # 30 - 50 = -20M; vende desplazado (10 -> 5M) y aún faltan -> ventas extra.
    assert plan.sell_substitute
    assert plan.extra_sells, "debe proponer ventas extra"


def test_bid_plan_no_factible():
    target = ps(1, 95, 200_000_000, pos=4)
    squad = [ps(10, 40, 1_000_000, pos=4)]
    plan = advisor.bid_plan(target, bid=200_000_000, disponible=1_000_000, squad=squad)
    assert not plan.feasible
