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
    verdict: str             # 📌 Pujando / 🟢 Fichar / 🟠 vende antes / 🟡 Espera/Dudoso / 🔴 Pasa / ⛔
    fit: str                 # ENCAJA / MEJORA / NO_ENCAJA
    fit_reason: str
    afford: str              # te_llega / vendiendo / no_te_llega
    max_buy: int
    expected: float
    trend_dir: str           # up / down / flat / new
    already_bidding: bool = False   # ya tienes una puja activa por él
    bid_amount: int = 0             # cuánto estás pujando
    note: str = ""                  # aviso (p. ej. ya pujas por uno mejor en esa posición)


# Diferencia mínima de score para considerar "claramente mejor" (evita empates).
_MEJOR_MARGEN = 5.0


def rank_market(market_scores: list[PlayerScore], squad_scores: list[PlayerScore],
                disponible: int, trend_map: dict | None = None,
                bids: dict | None = None) -> list[MarketPick]:
    """Ordena por prioridad de compra teniendo en cuenta rendimiento, encaje en tu
    plantilla, calendario, precio, tendencia Y tus PUJAS activas.

    `bids`: {player_id: (PlayerScore, importe)} de los jugadores por los que ya
    estás pujando. Se usa para: marcarlos, y para no recomendar fichar a un peor
    de la misma posición por la que ya vas a por uno mejor.
    """
    trend_map = trend_map or {}
    bids = bids or {}
    squad_ids = {s.player.id for s in squad_scores}
    bidding_ids = set(bids)

    # Mejor puja pendiente por posición (para no fichar un peor en esa línea).
    best_bid_pos: dict[int, PlayerScore] = {}
    for bs, _amt in bids.values():
        pos = bs.player.position_id
        if pos not in best_bid_pos or bs.score > best_bid_pos[pos].score:
            best_bid_pos[pos] = bs

    picks: list[MarketPick] = []
    for s in market_scores:
        pid = s.player.id
        already = pid in bidding_ids
        if pid in squad_ids:
            continue  # ya lo tienes
        if s.player.status in ("injured", "suspended", "out_of_league") and not already:
            continue  # no fichar lesionado/sancionado (salvo que ya pujes por él: se avisa)

        adv = market.price_advice(s)
        fit, motivo = advisor.team_fit(s, squad_scores)
        if disponible >= adv.max_buy:
            afford = "te_llega"
        else:
            plan = advisor.bid_plan(s, adv.max_buy, disponible, squad_scores)
            afford = "vendiendo" if plan.feasible else "no_te_llega"

        t = trend_map.get(pid)
        trend_dir = t.direction if t else "new"
        trend_bonus = 4 if trend_dir == "up" else (-4 if trend_dir == "down" else 0)
        priority = s.score * FIT_FACTOR.get(fit, 1.0) * AFFORD_FACTOR.get(afford, 0.5) + trend_bonus

        note = ""
        espera = False
        if not already:
            mejor = best_bid_pos.get(s.player.position_id)
            if mejor and mejor.player.id != pid and mejor.score > s.score + _MEJOR_MARGEN:
                # Ya vas a por uno mejor en esa posición: no tiene sentido fichar este.
                priority *= 0.45
                note = f"Ya pujas por {mejor.player.nickname} (mejor) en esa posición"
                espera = True

        priority = round(priority, 1)
        if s.player.status in ("injured", "suspended", "out_of_league"):
            verdict = "🔴 Lesionado/sancionado"
        elif already:
            verdict = "📌 Pujando"
        elif espera:
            verdict = "🟡 Espera"
        elif afford == "no_te_llega":
            verdict = "⛔ No te llega"
        elif s.signal == "VENDER" or fit == "NO_ENCAJA":
            verdict = "🔴 Pasa"
        elif afford == "te_llega" and (s.signal == "CHOLLO" or priority >= 55):
            verdict = "🟢 Fichar"
        elif afford == "vendiendo" and priority >= 60:
            verdict = "🟠 Sí, pero vende"
        else:
            verdict = "🟡 Dudoso"

        picks.append(MarketPick(
            ps=s, priority=priority, verdict=verdict, fit=fit, fit_reason=motivo,
            afford=afford, max_buy=adv.max_buy, expected=expected_points(s),
            trend_dir=trend_dir, already_bidding=already,
            bid_amount=int(bids[pid][1]) if already else 0, note=note))

    picks.sort(key=lambda p: p.priority, reverse=True)
    return picks
