"""Tests del ranking de 'mi mercado'."""
from src import mymarket
from src.api_client import Player
from src.engine import PlayerScore


def ps(pid, score, mv, pos=4, status="ok", signal="MANTENER"):
    p = Player(id=pid, nickname=f"J{pid}", position_id=pos, team_id=1, market_value=mv,
               points=score, average_points=5, last_season_points=0, status=status,
               image="", week_points={1: 5, 2: 5, 3: 5})
    return PlayerScore(player=p, score=score, signal=signal, rentabilidad=1.0,
                       forma=5.0, titularidad=1.0, facilidad_calendario=0.5)


def _squad():
    # once completo para que team_fit y bid_plan tengan contexto
    s = [ps(1, 60, 5_000_000, pos=1)]
    s += [ps(10 + i, 60, 5_000_000, pos=2) for i in range(4)]
    s += [ps(20 + i, 60, 5_000_000, pos=3) for i in range(4)]
    s += [ps(30 + i, 60, 5_000_000, pos=4) for i in range(2)]
    return s


def test_ranking_prioriza_bueno_asequible_que_encaja():
    squad = _squad()
    mercado = [
        ps(100, 90, 5_000_000, pos=4, signal="CHOLLO"),   # bueno, barato, mejora delantera
        ps(101, 90, 200_000_000, pos=4),                  # buenísimo pero carísimo
        ps(102, 20, 3_000_000, pos=4, signal="VENDER"),   # malo
    ]
    r = mymarket.rank_market(mercado, squad, disponible=10_000_000)
    ids = [p.ps.player.id for p in r]
    assert ids[0] == 100                       # el chollo asequible primero
    v = {p.ps.player.id: p for p in r}
    assert v[100].verdict == "🟢 Fichar"
    assert v[101].afford in ("vendiendo", "no_te_llega")
    assert v[102].verdict == "🔴 Pasa"


def test_excluye_los_que_ya_tienes_y_lesionados():
    squad = _squad()
    mercado = [ps(10, 90, 3_000_000, pos=2),               # ya en tu plantilla (id 10)
               ps(200, 90, 3_000_000, pos=4, status="injured")]
    r = mymarket.rank_market(mercado, squad, disponible=50_000_000)
    assert r == []


def test_bid_aware_espera_si_pujas_por_mejor():
    squad = _squad()
    mejor = ps(50, 90, 5_000_000, pos=4)   # gran delantero por el que YA pujas
    peor = ps(51, 60, 5_000_000, pos=4)    # delantero peor que te sale en el mercado
    bids = {50: (mejor, 5_000_000)}
    r = mymarket.rank_market([mejor, peor], squad, disponible=50_000_000, bids=bids)
    v = {p.ps.player.id: p for p in r}
    assert v[50].verdict == "📌 Pujando" and v[50].already_bidding
    assert v[50].bid_amount == 5_000_000
    assert v[51].verdict == "🟡 Espera"       # no fiches el peor, ya vas a por el mejor
    assert v[51].note
    assert r[0].ps.player.id == 50            # el mejor (que ya pujas) va primero


def test_sin_bids_funciona_igual():
    squad = _squad()
    t = [ps(100, 90, 3_000_000, pos=4, signal="CHOLLO")]
    r = mymarket.rank_market(t, squad, disponible=10_000_000)   # bids por defecto None
    assert r[0].verdict == "🟢 Fichar" and not r[0].already_bidding


def test_no_te_llega_marcado():
    squad = _squad()
    mercado = [ps(300, 95, 300_000_000, pos=4)]            # imposible ni vendiendo
    r = mymarket.rank_market(mercado, squad, disponible=1_000_000)
    assert r[0].verdict == "⛔ No te llega"
