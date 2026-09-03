"""Análisis de "mi mercado": ranking de prioridad de compra.

Dado los jugadores que te salen en el mercado ahora, tu plantilla y tu dinero,
ordena por prioridad de fichaje teniendo en cuenta: rendimiento (score), encaje
en tu equipo (lo que te hace falta reforzar), si te llega el dinero (con o sin
vender) y la tendencia de su valor.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import advisor, market
from .engine import PlayerScore
from .lineup import expected_points

FIT_FACTOR = {"MEJORA": 1.15, "ENCAJA": 1.0, "NO_ENCAJA": 0.55}
AFFORD_FACTOR = {"te_llega": 1.0, "vendiendo": 0.8, "no_te_llega": 0.3}


@dataclass
class MarketPick:
    ps: PlayerScore
    priority: float          # 0-100+ para ordenar
    verdict: str             # 🟢 Fichar / 🟡 Dudoso / 🔴 Pasa / ⛔ No te llega
    fit: str                 # ENCAJA / MEJORA / NO_ENCAJA
    fit_reason: str
    afford: str              # te_llega / vendiendo / no_te_llega
    max_buy: int
    expected: float
    trend_dir: str           # up / down / flat / new


def rank_market(market_scores: list[PlayerScore], squad_scores: list[PlayerScore],
                disponible: int, trend_map: dict | None = None) -> list[MarketPick]:
    trend_map = trend_map or {}
    squad_ids = {s.player.id for s in squad_scores}
    picks: list[MarketPick] = []

    for s in market_scores:
        if s.player.id in squad_ids:
            continue  # ya lo tienes
        if s.player.status in ("injured", "suspended", "out_of_league"):
            continue  # no fichar lesionado/sancionado
        adv = market.price_advice(s)
        fit, motivo = advisor.team_fit(s, squad_scores)

        if disponible >= adv.max_buy:
            afford = "te_llega"
        else:
            plan = advisor.bid_plan(s, adv.max_buy, disponible, squad_scores)
            afford = "vendiendo" if plan.feasible else "no_te_llega"

        t = trend_map.get(s.player.id)
        trend_dir = t.direction if t else "new"
        trend_bonus = 4 if trend_dir == "up" else (-4 if trend_dir == "down" else 0)

        priority = round(s.score * FIT_FACTOR.get(fit, 1.0)
                         * AFFORD_FACTOR.get(afford, 0.5) + trend_bonus, 1)

        if afford == "no_te_llega":
            verdict = "⛔ No te llega"
        elif s.signal == "VENDER" or fit == "NO_ENCAJA":
            verdict = "🔴 Pasa"
        elif afford == "te_llega" and (s.signal == "CHOLLO" or priority >= 55):
            verdict = "🟢 Fichar"          # puedes ficharlo ya, merece la pena
        elif afford == "vendiendo" and priority >= 60:
            verdict = "🟠 Sí, pero vende"   # vale la pena, pero tienes que vender antes
        else:
            verdict = "🟡 Dudoso"

        picks.append(MarketPick(ps=s, priority=priority, verdict=verdict, fit=fit,
                                fit_reason=motivo, afford=afford, max_buy=adv.max_buy,
                                expected=expected_points(s), trend_dir=trend_dir))

    picks.sort(key=lambda p: p.priority, reverse=True)
    return picks
