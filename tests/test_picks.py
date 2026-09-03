"""Tests de chollos de la jornada y próximos rivales."""
from src import engine, picks
from src.api_client import Fixture, Player
from src.engine import PlayerScore


def ps(pid, mv, forma, pos=4, status="ok"):
    p = Player(id=pid, nickname=f"J{pid}", position_id=pos, team_id=1, market_value=mv,
               points=int(forma * 3), average_points=forma, last_season_points=0,
               status=status, image="", week_points={1: forma, 2: forma, 3: forma})
    return PlayerScore(player=p, score=50, signal="", rentabilidad=1.0, forma=forma,
                       titularidad=1.0, facilidad_calendario=0.5)


def test_chollos_ordena_por_valor_por_millon():
    barato_bueno = ps(1, 2_000_000, 8)     # mucho rendimiento por poco dinero
    caro_bueno = ps(2, 40_000_000, 9)      # rinde pero carísimo
    barato_flojo = ps(3, 2_000_000, 1)
    res = picks.chollos_jornada([caro_bueno, barato_flojo, barato_bueno], n=3)
    assert res[0].player.id == 1           # el barato y bueno primero


def test_chollos_excluye_lesionados_y_filtra_precio():
    lesionado = ps(1, 1_000_000, 9, status="injured")
    caro = ps(2, 30_000_000, 9)
    barato = ps(3, 3_000_000, 6)
    res = picks.chollos_jornada([lesionado, caro, barato], max_price=5_000_000)
    ids = [s.player.id for s in res]
    assert 1 not in ids and 2 not in ids and 3 in ids


def test_chollos_filtra_por_posicion():
    d = ps(1, 3_000_000, 6, pos=2)
    m = ps(2, 3_000_000, 6, pos=3)
    res = picks.chollos_jornada([d, m], position_id=2)
    assert [s.player.id for s in res] == [1]


def test_next_opponents():
    fx = [
        Fixture(1, 3, "d", 10, 20, 1, 0, engine.MATCH_FINISHED),   # ya jugado
        Fixture(2, 4, "d", 10, 30, None, None, 1),                 # próximo (local)
        Fixture(3, 5, "d", 40, 10, None, None, 1),                 # siguiente (visitante)
    ]
    op = engine.next_opponents(10, fx, n=2)
    assert op[0] == (30, True, 4)     # rival 30, en casa, jornada 4
    assert op[1] == (40, False, 5)    # rival 40, fuera, jornada 5
