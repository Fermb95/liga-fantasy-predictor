"""Tests del motor de valoración (Bloque 2)."""
import pytest

from src import db, engine
from src.api_client import Fixture, Player


# ---- Helpers ----------------------------------------------------------------
def mk_player(pid, pos=3, team=15, mv=5_000_000, points=40, status="ok", wp=None):
    return Player(id=pid, nickname=f"J{pid}", position_id=pos, team_id=team,
                  market_value=mv, points=points, average_points=points / 3,
                  last_season_points=0, status=status, image="", week_points=wp or {})


# ---- Métricas unitarias -----------------------------------------------------
def test_recent_form_pondera_mas_lo_reciente():
    subiendo = engine.recent_form({1: 0, 2: 5, 3: 10})   # racha al alza
    bajando = engine.recent_form({1: 10, 2: 5, 3: 0})    # racha a la baja
    assert subiendo > bajando


def test_recent_form_solo_ultimas_n():
    assert engine.recent_form({1: 20, 2: 0, 3: 0, 4: 0}, n=3) == pytest.approx(0.0)


def test_titularidad():
    assert engine.titularidad({1: 8, 2: 0, 3: 6, 4: 5}) == pytest.approx(0.75)
    assert engine.titularidad({}) == 0.0


def test_rentabilidad_y_division_por_cero():
    assert engine.rentabilidad(50, 10_000_000) == pytest.approx(5.0)
    assert engine.rentabilidad(50, 0) == 0.0


def test_team_strength_ganador_mayor_que_perdedor():
    fx = [
        Fixture(1, 1, "d", 10, 20, 3, 0, engine.MATCH_FINISHED),  # 10 gana
        Fixture(2, 2, "d", 10, 30, 2, 1, engine.MATCH_FINISHED),  # 10 gana
        Fixture(3, 1, "d", 20, 30, 0, 2, engine.MATCH_FINISHED),  # 30 gana a 20
    ]
    s = engine.team_strength(fx)
    assert s[10] > s[20]          # 10 gana todo, 20 pierde todo
    assert s[10] == pytest.approx(1.0)
    assert s[20] == pytest.approx(0.0)


def test_upcoming_ease_rival_debil_es_mas_facil():
    strength = {100: 1.0, 1: 0.0, 2: 0.0}  # 100 muy fuerte, 1 y 2 débiles
    # Equipo 50 juega contra rival débil (1) vs contra rival fuerte (100).
    fx_facil = [Fixture(1, 4, "d", 50, 1, None, None, 1)]
    fx_dificil = [Fixture(2, 4, "d", 50, 100, None, None, 1)]
    assert engine.upcoming_ease(50, fx_facil, strength) > engine.upcoming_ease(50, fx_dificil, strength)


# ---- Score compuesto --------------------------------------------------------
def test_crack_en_forma_supera_a_lesionado_caro():
    fx = []  # sin calendario -> facilidad neutra para todos
    crack = mk_player(1, mv=5_000_000, points=60, status="ok", wp={1: 12, 2: 14, 3: 16})
    lesionado = mk_player(2, mv=30_000_000, points=10, status="injured", wp={1: 2, 2: 0, 3: 1})
    relleno = mk_player(3, mv=8_000_000, points=20, status="ok", wp={1: 3, 2: 2, 3: 4})
    scores = {s.player.id: s for s in engine.score_players([crack, lesionado, relleno], fx)}
    assert scores[1].score > scores[2].score
    assert scores[2].signal == "VENDER"      # lesionado -> vender
    assert scores[1].signal == "CHOLLO"      # barato y en forma -> chollo


def test_score_en_rango_0_100_y_normaliza_por_posicion():
    fx = []
    jugadores = [mk_player(i, pos=(i % 4) + 1, mv=1_000_000 * (i + 1),
                           points=10 * i, wp={1: i, 2: i, 3: i}) for i in range(1, 9)]
    scores = engine.score_players(jugadores, fx)
    assert all(0 <= s.score <= 100 for s in scores)
    # El mejor de cada posición debería acercarse a 100 (min-max por grupo).
    por_pos = {}
    for s in scores:
        por_pos.setdefault(s.player.position_id, []).append(s.score)
    for vals in por_pos.values():
        assert max(vals) == pytest.approx(100.0)


def test_pesos_personalizables_cambian_el_orden():
    fx = []
    # A: barato pero flojo de forma. B: caro pero en gran forma.
    a = mk_player(1, mv=1_000_000, points=30, wp={1: 3, 2: 3, 3: 3})
    b = mk_player(2, mv=20_000_000, points=30, wp={1: 15, 2: 16, 3: 18})
    solo_rent = engine.Weights(rentabilidad=1, forma=0, titularidad=0, calendario=0)
    solo_forma = engine.Weights(rentabilidad=0, forma=1, titularidad=0, calendario=0)
    r = {s.player.id: s.score for s in engine.score_players([a, b], fx, solo_rent)}
    f = {s.player.id: s.score for s in engine.score_players([a, b], fx, solo_forma)}
    assert r[1] > r[2]   # por rentabilidad gana el barato
    assert f[2] > f[1]   # por forma gana el que está fino


# ---- Coherencia sobre datos REALES ------------------------------------------
@pytest.mark.live
def test_coherencia_sobre_bd_real():
    """Sobre los datos oficiales ya ingeridos: los mejores scores son jugadores
    disponibles y con forma; ningún lesionado se cuela como CHOLLO."""
    conn = db.connect()
    try:
        players = db.get_players(conn)
        fixtures = db.get_fixtures(conn)
    finally:
        conn.close()
    if not players:
        pytest.skip("BD vacía: ejecuta 'py -m src.ingest' primero")

    scores = engine.score_players(players, fixtures)
    top20 = scores[:20]
    # Ningún CHOLLO puede estar lesionado/sancionado.
    assert all(s.player.status == "ok" for s in scores if s.signal == "CHOLLO")
    # La mayoría del top20 son jugadores disponibles.
    assert sum(1 for s in top20 if s.player.status == "ok") >= 16
    # Todos los scores en rango.
    assert all(0 <= s.score <= 100 for s in scores)
