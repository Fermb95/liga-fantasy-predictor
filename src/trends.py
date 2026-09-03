"""Tendencia del valor de mercado (sube / baja / estable).

Compara el último snapshot de valor con el anterior para saber si un jugador se
está revalorizando (compra antes de que suba) o depreciando (vende antes de que
baje). Los snapshots los guarda la ingesta en la tabla value_history.
"""
from __future__ import annotations

from dataclasses import dataclass

# Umbral (en %) por debajo del cual consideramos el precio "estable".
FLAT_PCT = 0.5


@dataclass
class Trend:
    current: int
    previous: int | None
    change: int          # euros
    pct: float           # variación %

    @property
    def direction(self) -> str:
        if self.previous is None:
            return "new"
        if self.pct > FLAT_PCT:
            return "up"
        if self.pct < -FLAT_PCT:
            return "down"
        return "flat"

    @property
    def emoji(self) -> str:
        return {"up": "📈", "down": "📉", "flat": "➡️", "new": "•"}[self.direction]

    @property
    def label(self) -> str:
        return {"up": "subiendo", "down": "bajando", "flat": "estable",
                "new": "sin histórico"}[self.direction]


def compute_trends(latest: dict[int, int], prev: dict[int, int]) -> dict[int, Trend]:
    """Función pura: dado el valor más reciente y el anterior por jugador,
    devuelve la tendencia de cada uno."""
    out: dict[int, Trend] = {}
    for pid, cur in latest.items():
        p = prev.get(pid)
        if p is None or p == 0:
            out[pid] = Trend(current=cur, previous=None, change=0, pct=0.0)
        else:
            change = cur - p
            out[pid] = Trend(current=cur, previous=p, change=change,
                             pct=round(change / p * 100, 2))
    return out


def get_trends(conn) -> dict[int, Trend]:
    """Tendencias a partir de la BD (dos snapshots más recientes)."""
    latest, prev = _two_latest(conn)
    return compute_trends(latest, prev)


def _two_latest(conn):
    from . import db
    return db.value_history_two_latest(conn)
