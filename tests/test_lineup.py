"""Tests de capitán y once ideal (Bloque 7)."""
from src import lineup
from src.api_client import Player
from src.engine import PlayerScore


def ps(pid, pos, forma, status="ok", cal=0.5):
    p = Player(id=pid, nickname=f"J{pid}", position_id=pos, team_id=1, market_value=1_000_000,
               points=int(forma * 3), average_points=forma, last_season_points=0,
               status=status, image="", week_points={1: forma, 2: forma, 3: forma})
    return PlayerScore(player=p, score=50, signal="MANTENER", rentabilidad=1.0,
                       forma=forma, titularidad=1.0, facilidad_calendario=cal)


def squad_completa():
    # 2 POR, 5 DEF, 5 MID, 3 DEL (suficiente para varias formaciones)
    s = []
    s += [ps(1, lineup.GK, 6), ps(2, lineup.GK, 4)]
    s += [ps(10 + i, lineup.DEF, 8 - i) for i in range(5)]
    s += [ps(20 + i, lineup.MID, 9 - i) for i in range(5)]
    s += [ps(30 + i, lineup.FWD, 10 - i) for i in range(3)]
    return s


def test_expected_points_calendario_y_estado():
    facil = ps(1, lineup.FWD, 10, cal=1.0)
    dificil = ps(2, lineup.FWD, 10, cal=0.0)
    assert lineup.expected_points(facil) > lineup.expected_points(dificil)
    lesionado = ps(3, lineup.FWD, 10, status="injured")
    assert lineup.expected_points(lesionado) == 0.0


def test_capitan_es_el_de_mayor_esperado():
    squad = squad_completa()
    cap = lineup.best_captain(squad)
    # El delantero 30 tiene forma 10 y calendario neutro -> el mayor esperado.
    assert cap.player.id == 30


def test_capitan_ignora_lesionados():
    squad = [ps(1, lineup.FWD, 20, status="injured"), ps(2, lineup.FWD, 5)]
    assert lineup.best_captain(squad).player.id == 2


def test_once_ideal_valido_y_con_portero():
    res = lineup.optimal_lineup(squad_completa())
    assert res is not None
    d, m, f = res.formation
    assert (d, m, f) in lineup.FORMATIONS
    assert len(res.xi) == 11
    porteros = [s for s in res.xi if s.player.position_id == lineup.GK]
    assert len(porteros) == 1
    # composición coherente con la formación
    assert sum(1 for s in res.xi if s.player.position_id == lineup.DEF) == d
    assert sum(1 for s in res.xi if s.player.position_id == lineup.FWD) == f
    assert res.captain is not None and res.captain in res.xi


def test_once_ideal_elige_mejores_jugadores():
    squad = squad_completa()
    res = lineup.optimal_lineup(squad)
    # El peor defensa (id 14, forma 4) no debería ser titular si sobran defensas
    # en formaciones de 3-4 defensas... comprobamos que el mejor delantero está.
    ids_xi = {s.player.id for s in res.xi}
    assert 30 in ids_xi  # mejor delantero siempre entra


def test_sin_portero_no_hay_alineacion():
    squad = [ps(10 + i, lineup.DEF, 5) for i in range(5)]
    assert lineup.optimal_lineup(squad) is None


def test_incluye_entrenador():
    squad = squad_completa() + [ps(90, lineup.COACH, 7), ps(91, lineup.COACH, 3)]
    res = lineup.optimal_lineup(squad)
    assert res.coach is not None
    assert res.coach.player.id == 90          # el entrenador con más pts esperados
    # El entrenador no ocupa hueco de jugador de campo en el once.
    assert all(s.player.position_id != lineup.COACH for s in res.xi)


def test_capitan_no_es_entrenador():
    squad = squad_completa() + [ps(90, lineup.COACH, 50)]  # entrenador con "forma" alta
    cap = lineup.best_captain(squad)
    assert cap.player.position_id != lineup.COACH
