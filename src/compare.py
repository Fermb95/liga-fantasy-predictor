"""Bloque 12 — Comparador de jugadores y simulador de pujas múltiples.

Permite valorar varios objetivos a la vez y simular "¿y si pujo por este y por
este otro?": coste total, si te llega, a quién vender para cubrirlo, dinero
resultante y si cada fichaje merece la pena (veredicto + encaje).

Módulo puro sobre PlayerScore (de engine.score_players).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import advisor, market
from .engine import PlayerScore

POS_NOMBRE = {1: "portería", 2: "defensa", 3: "medio", 4: "delantera"}


@dataclass
class TargetEval:
    ps: PlayerScore
    bid: int
    max_buy: int
    verdict: str          # CHOLLO / MANTENER / VENDER (del motor)
    fit: str              # ENCAJA / MEJORA / NO_ENCAJA
    fit_reason: str
    worth: bool           # ¿merece la pena ficharlo?
    overbid: bool         # ¿pujas por encima del máximo recomendado?


@dataclass
class MultiBidPlan:
    targets: list[TargetEval]
    total_cost: int
    disponible: int
    affordable: bool
    shortfall: int
    sells: list[PlayerScore] = field(default_factory=list)
    cash_after: int = 0
    feasible: bool = True
    notes: list[str] = field(default_factory=list)


def _eval_target(ps: PlayerScore, bid: int, squad: list[PlayerScore]) -> TargetEval:
    adv = market.price_advice(ps)
    fit, reason = advisor.team_fit(ps, squad)
    worth = ps.signal != "VENDER" and fit != "NO_ENCAJA"
    return TargetEval(ps=ps, bid=bid, max_buy=adv.max_buy, verdict=ps.signal,
                      fit=fit, fit_reason=reason, worth=worth, overbid=bid > adv.max_buy)


def multi_bid_plan(targets: list[tuple[PlayerScore, int]], disponible: int,
                   squad: list[PlayerScore]) -> MultiBidPlan:
    """Simula pujar por varios jugadores a la vez."""
    evals = [_eval_target(ps, bid, squad) for ps, bid in targets]
    total = sum(bid for _, bid in targets)
    plan = MultiBidPlan(
        targets=evals, total_cost=total, disponible=disponible,
        affordable=disponible >= total, shortfall=max(0, total - disponible),
    )

    cash = disponible - total
    if cash < 0:
        target_ids = {ps.player.id for ps, _ in targets}
        candidatos = sorted([s for s in squad if s.player.id not in target_ids],
                            key=lambda s: s.score)
        for s in candidatos:
            if cash >= 0:
                break
            cash += advisor.sell_advice(s).min_accept
            plan.sells.append(s)
    plan.cash_after = cash
    plan.feasible = cash >= 0

    # Avisos útiles.
    for te in evals:
        if te.overbid:
            plan.notes.append(f"Pujas por {te.ps.player.nickname} por encima de su máximo "
                              f"recomendado ({te.max_buy} €).")
        if not te.worth:
            motivo = "no rinde" if te.verdict == "VENDER" else "no te encaja ahora"
            plan.notes.append(f"{te.ps.player.nickname}: {motivo} → quizá mejor pasar.")

    # Conflicto de posiciones entre los propios objetivos.
    por_pos: dict[int, int] = {}
    for ps, _ in targets:
        por_pos[ps.player.position_id] = por_pos.get(ps.player.position_id, 0) + 1
    for pos, n in por_pos.items():
        if n > 1:
            plan.notes.append(f"Fichas {n} de {POS_NOMBRE.get(pos, 'esa posición')} a la vez: "
                              "asegúrate de que quieres reforzar tanto ahí.")

    if not plan.feasible:
        plan.notes.append(f"No te llega ni vendiendo: faltan {-cash}.")
    return plan


def best_of(targets: list[PlayerScore]) -> PlayerScore | None:
    """El mejor objetivo por score (para destacar en la comparación)."""
    return max(targets, key=lambda s: s.score) if targets else None
