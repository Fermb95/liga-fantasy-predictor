"""Tests del recomendador personal (Bloque 3a)."""
import pytest

from src import db, engine, recommender
from src.api_client import Player
from src.engine import PlayerScore


def mk_score(pid, score, mv, status="ok", signal="MANTENER", pos=3, forma=5.0):
    p = Player(id=pid, nickname=f"J{pid}", position_id=pos, team_id=1, market_value=mv,
               points=int(forma * 3), average_points=forma, last_season_points=0,
               status=status, image="", week_points={1: forma, 2: forma, 3: forma})
    return PlayerScore(player=p, score=score, signal=signal, rentabilidad=1.0,
                       forma=forma, titularidad=1.0, facilidad_calendario=0.5)


def test_comprar_solo_asequibles_y_buenos():
    scores = [
        mk_score(1, 80, 5_000_000),    # bueno y asequible -> COMPRAR
        mk_score(2, 85, 50_000_000),   # bueno pero caro -> no cabe
        mk_score(3, 50, 3_000_000),    # asequible pero mediocre -> no
    ]
    rec = recommender.recommend(scores, budget=10_000_000, squad_ids=[])
    ids = [s.player.id for s in rec.comprar]
    assert ids == [1]


def test_vender_tus_jugadores_malos():
    scores = [
        mk_score(1, 20, 5_000_000, signal="VENDER"),        # tuyo y malo -> VENDER
        mk_score(2, 75, 8_000_000, signal="CHOLLO"),        # tuyo y bueno -> MANTENER
        mk_score(3, 70, 9_000_000, status="injured"),       # tuyo lesionado -> VENDER
    ]
    rec = recommender.recommend(scores, budget=0, squad_ids=[1, 2, 3])
    vender_ids = {s.player.id for s in rec.vender}
    mantener_ids = {s.player.id for s in rec.mantener}
    assert vender_ids == {1, 3}
    assert mantener_ids == {2}


def test_no_vender_unico_portero():
    # Portero flojo (señal VENDER) + resto para formar un 3-4-3.
    squad = [mk_score(1, 10, 5_000_000, signal="VENDER", pos=1)]
    squad += [mk_score(10 + i, 60, 5_000_000, pos=2) for i in range(3)]
    squad += [mk_score(20 + i, 60, 5_000_000, pos=3) for i in range(4)]
    squad += [mk_score(30 + i, 60, 5_000_000, pos=4) for i in range(3)]
    ids = [s.player.id for s in squad]
    rec = recommender.recommend(squad, budget=0, squad_ids=ids)
    assert 1 in rec.imprescindibles                       # es imprescindible
    assert all(s.player.id != 1 for s in rec.vender)      # NO se recomienda venderlo


def test_con_dos_porteros_si_se_puede_vender_el_malo():
    squad = [mk_score(1, 10, 5_000_000, signal="VENDER", pos=1),
             mk_score(2, 90, 5_000_000, pos=1)]            # segundo portero
    squad += [mk_score(10 + i, 60, 5_000_000, pos=2) for i in range(3)]
    squad += [mk_score(20 + i, 60, 5_000_000, pos=3) for i in range(4)]
    squad += [mk_score(30 + i, 60, 5_000_000, pos=4) for i in range(3)]
    ids = [s.player.id for s in squad]
    rec = recommender.recommend(squad, budget=0, squad_ids=ids)
    assert 1 not in rec.imprescindibles
    assert any(s.player.id == 1 for s in rec.vender)       # el portero malo sí se vende


def test_no_recomienda_comprar_lo_que_ya_tienes():
    scores = [mk_score(1, 90, 5_000_000)]
    rec = recommender.recommend(scores, budget=100_000_000, squad_ids=[1])
    assert all(s.player.id != 1 for s in rec.comprar)


def test_no_compra_lesionados():
    scores = [mk_score(1, 90, 1_000_000, status="injured")]
    rec = recommender.recommend(scores, budget=100_000_000, squad_ids=[])
    assert rec.comprar == []


def test_ignorar_son_caros_que_no_rinden():
    scores = [
        mk_score(1, 20, 30_000_000, pos=4),   # caro para su pos y flojo -> IGNORAR
        mk_score(2, 20, 1_000_000, pos=4),    # flojo pero barato -> no es trampa
    ]
    rec = recommender.recommend(scores, budget=100_000_000, squad_ids=[])
    ignorar_ids = {s.player.id for s in rec.ignorar}
    assert 1 in ignorar_ids
    assert 2 not in ignorar_ids


def test_listas_acotadas():
    scores = [mk_score(i, 90, 1_000_000) for i in range(50)]
    rec = recommender.recommend(scores, budget=100_000_000, squad_ids=[], max_por_lista=15)
    assert len(rec.comprar) == 15


@pytest.mark.live
def test_recomendacion_sobre_bd_real():
    conn = db.connect()
    try:
        players = db.get_players(conn)
        fixtures = db.get_fixtures(conn)
    finally:
        conn.close()
    if not players:
        pytest.skip("BD vacía: ejecuta 'py -m src.ingest' primero")

    scores = engine.score_players(players, fixtures)
    # Simula: 5M de presupuesto, sin plantilla definida.
    rec = recommender.recommend(scores, budget=5_000_000, squad_ids=[])
    # Todo lo recomendado comprar debe caber en el presupuesto y estar disponible.
    assert all(s.player.market_value <= 5_000_000 for s in rec.comprar)
    assert all(s.player.status == "ok" for s in rec.comprar)
    assert len(rec.comprar) > 0
