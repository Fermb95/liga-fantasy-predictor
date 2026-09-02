"""Bloque 7 — Puntos esperados de la jornada, capitán y once ideal.

A partir de los scores del motor (que ya incluyen forma reciente y facilidad de
calendario), estima los PUNTOS ESPERADOS de cada jugador para la próxima jornada
y con ello:
  - elige el mejor CAPITÁN (dobla puntos → el de mayor puntuación esperada),
  - arma el ONCE IDEAL de tu plantilla probando las formaciones válidas.

Módulo puro: recibe PlayerScore (de engine.score_players) y devuelve resultados.
"""
from __future__ import annotations

from dataclasses import dataclass

from .engine import PlayerScore

# Portero=1, Defensa=2, Medio=3, Delantero=4 (Entrenador=5 no entra en el once).
GK, DEF, MID, FWD = 1, 2, 3, 4

# Formaciones oficiales (defensas, medios, delanteros) + 1 portero.
FORMATIONS = [
    (3, 4, 3), (3, 5, 2), (4, 3, 3), (4, 4, 2), (4, 5, 1), (5, 3, 2), (5, 4, 1),
]

# Probabilidad de jugar según estado (afecta a los puntos esperados).
PLAY_FACTOR = {"ok": 1.0, "doubtful": 0.5, "injured": 0.0, "suspended": 0.0, "out_of_league": 0.0}


def expected_points(ps: PlayerScore) -> float:
    """Puntos esperados del jugador para la próxima jornada."""
    p = ps.player
    # Base: forma reciente; si no ha jugado, su media o el histórico repartido.
    base = ps.forma if ps.forma > 0 else max(p.average_points, p.last_season_points / 38.0)
    # Calendario: rival fácil sube, difícil baja (0.85 a 1.15).
    fixture_mult = 0.85 + 0.30 * ps.facilidad_calendario
    play = PLAY_FACTOR.get(p.status, 1.0)
    return round(base * fixture_mult * play, 2)


@dataclass
class LineupResult:
    formation: tuple[int, int, int]      # (def, med, del)
    xi: list[PlayerScore]                # once titular
    bench: list[PlayerScore]             # suplentes
    captain: PlayerScore | None
    total_expected: float                # suma de puntos esperados (con capitán x2)


def best_captain(squad: list[PlayerScore]) -> PlayerScore | None:
    """El jugador de mayor puntuación esperada (su capitanía renta más)."""
    jugables = [s for s in squad if PLAY_FACTOR.get(s.player.status, 1.0) > 0]
    if not jugables:
        return None
    return max(jugables, key=expected_points)


def optimal_lineup(squad: list[PlayerScore]) -> LineupResult | None:
    """Mejor alineación posible con tu plantilla, probando las formaciones válidas."""
    by_pos: dict[int, list[PlayerScore]] = {GK: [], DEF: [], MID: [], FWD: []}
    for s in squad:
        if s.player.position_id in by_pos:
            by_pos[s.player.position_id].append(s)
    for pos in by_pos:
        by_pos[pos].sort(key=expected_points, reverse=True)

    if not by_pos[GK]:
        return None  # sin portero no hay alineación

    mejor: LineupResult | None = None
    portero = by_pos[GK][0]
    for d, m, f in FORMATIONS:
        if len(by_pos[DEF]) < d or len(by_pos[MID]) < m or len(by_pos[FWD]) < f:
            continue  # no tienes jugadores suficientes para esta formación
        xi = [portero] + by_pos[DEF][:d] + by_pos[MID][:m] + by_pos[FWD][:f]
        total = sum(expected_points(s) for s in xi)
        if mejor is None or total > mejor.total_expected:
            usados = {s.player.id for s in xi}
            bench = sorted([s for s in squad if s.player.id not in usados],
                           key=expected_points, reverse=True)
            mejor = LineupResult((d, m, f), xi, bench, None, round(total, 2))

    if mejor is None:
        return None
    # Capitán dentro del once (el de mayor puntuación esperada) → suma x2 su aporte.
    cap = max(mejor.xi, key=expected_points)
    mejor.captain = cap
    mejor.total_expected = round(mejor.total_expected + expected_points(cap), 2)
    return mejor
