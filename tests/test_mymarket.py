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


def test_venta_libera_dinero_para_fichar():
    squad = _squad()
    objetivo = ps(400, 90, 12_000_000, pos=4, signal="CHOLLO")  # cuesta más de lo que tienes
    en_venta = ps(30, 40, 10_000_000, pos=4)   # lo tienes a la venta por 10M
    listings = {30: (en_venta, 10_000_000)}
    # Con 5M no llega; vendiendo el listado (5+10=15M) sí.
    r = mymarket.rank_market([objetivo], squad, disponible=5_000_000, listings=listings)
    v = {p.ps.player.id: p for p in r}
    assert v[400].afford == "vendiendo"        # te llega gracias a la venta
    assert v[400].verdict in ("🟢 Fichar", "🟠 Sí, pero vende")


def test_no_fichar_peor_que_lo_que_vendes():
    squad = _squad()
    en_venta = ps(30, 90, 8_000_000, pos=4)    # gran delantero que tienes en venta
    peor = ps(500, 60, 5_000_000, pos=4)       # del mercado, peor que el que vendes
    listings = {30: (en_venta, 8_000_000)}
    r = mymarket.rank_market([peor], squad, disponible=50_000_000, listings=listings)
    v = {p.ps.player.id: p for p in r}
    assert v[500].verdict == "🟡 Mejor quédate el tuyo"
    assert v[500].note


def test_fichar_mejora_a_lo_que_vendes():
    squad = _squad()
    en_venta = ps(30, 55, 5_000_000, pos=4)    # flojo, lo tienes a la venta
    mejor = ps(600, 90, 5_000_000, pos=4, signal="CHOLLO")  # del mercado, mucho mejor
    listings = {30: (en_venta, 5_000_000)}
    r = mymarket.rank_market([mejor], squad, disponible=50_000_000, listings=listings)
    v = {p.ps.player.id: p for p in r}
    assert v[600].upgrades_listing
    assert "en venta" in v[600].note


def test_review_listings_vender_si_hay_mejor():
    en_venta = ps(30, 55, 5_000_000, pos=4)
    mercado = [ps(600, 90, 5_000_000, pos=4), ps(601, 20, 3_000_000, pos=4)]
    listings = {30: (en_venta, 5_000_000)}
    rev = mymarket.review_listings(listings, mercado, disponible=5_000_000)
    assert len(rev) == 1
    assert rev[0].verdict == "🔁 Vender y fichar mejor"
    assert rev[0].better and rev[0].better[0].player.id == 600


def test_review_listings_quedatelo_si_nada_mejor():
    en_venta = ps(30, 90, 8_000_000, pos=4)    # ya es bueno
    mercado = [ps(700, 60, 5_000_000, pos=4)]  # peor que él
    listings = {30: (en_venta, 8_000_000)}
    rev = mymarket.review_listings(listings, mercado, disponible=50_000_000)
    assert rev[0].verdict == "🔒 Quédatelo"
    assert rev[0].better == []
