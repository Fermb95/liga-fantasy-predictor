"""Chollos de la jornada: mejor relación puntos esperados / precio.

Selecciona jugadores disponibles que más rinden por cada millón de euros de cara
a la próxima jornada (forma + calendario), ideal para reforzar barato.
"""
from __future__ import annotations

from .engine import PlayerScore
from .lineup import expected_points


def value_per_million(s: PlayerScore) -> float:
    mv = s.player.market_value
    if mv <= 0:
        return 0.0
    return expected_points(s) / (mv / 1_000_000)


def chollos_jornada(scores: list[PlayerScore], max_price: int | None = None,
                    position_id: int | None = None, n: int = 12) -> list[PlayerScore]:
    """Mejores chollos: disponibles, ordenados por puntos esperados por millón."""
    cand = [s for s in scores
            if s.player.status == "ok" and s.player.market_value > 0
            and expected_points(s) > 0]
    if max_price is not None:
        cand = [s for s in cand if s.player.market_value <= max_price]
    if position_id is not None:
        cand = [s for s in cand if s.player.position_id == position_id]
    cand.sort(key=value_per_million, reverse=True)
    return cand[:n]
