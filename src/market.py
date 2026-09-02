"""Bloque 8 — Precios recomendados y simulador de fichajes.

Para cada jugador calcula:
  - precio justo (valor de mercado actual),
  - hasta cuánto pujar para ficharlo (mejor jugador → merece más sobreprecio),
  - a cuánto venderlo,
  - qué cláusula ponerle para protegerlo.

Y un simulador de fichaje: dado un objetivo y tu dinero, dice si te llega y, si
no, a quién vender para financiarlo (sacrificando lo menos valioso).

Módulo puro sobre PlayerScore (de engine.score_players).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .engine import PlayerScore


@dataclass
class PriceAdvice:
    fair_value: int        # valor de mercado actual (lo que da el sistema)
    max_buy: int           # puja máxima recomendada para ficharlo
    sell_ask: int          # a cuánto ofrecerlo si lo vendes
    suggested_clause: int  # cláusula recomendada para blindarlo


def price_advice(ps: PlayerScore) -> PriceAdvice:
    fair = int(ps.player.market_value)
    q = ps.score / 100.0  # calidad relativa 0..1
    # Cuanto mejor es el jugador, más sobreprecio justifica y más hay que blindarlo.
    max_buy = int(round(fair * (1 + 0.05 + 0.15 * q)))          # +5% a +20%
    sell_ask = int(round(fair * (1 + 0.10 * q)))                # hasta +10%
    suggested_clause = int(round(fair * (1.5 + 1.5 * q)))       # x1.5 a x3
    return PriceAdvice(fair_value=fair, max_buy=max_buy,
                       sell_ask=sell_ask, suggested_clause=suggested_clause)


@dataclass
class FinancingPlan:
    target: PlayerScore
    price: int                       # lo que costaría (puja máxima recomendada)
    budget: int
    affordable_now: bool             # ¿te llega solo con el dinero?
    shortfall: int                   # cuánto te falta (0 si te llega)
    sells: list[PlayerScore] = field(default_factory=list)  # a quién vender
    budget_after: int = 0            # dinero restante tras comprar (y vender)
    feasible: bool = True            # ¿es posible aunque vendas?
    suggested_clause: int = 0        # cláusula recomendada tras ficharlo


def financing_plan(target: PlayerScore, budget: int,
                   squad: list[PlayerScore]) -> FinancingPlan:
    """Plan para fichar a `target`: ¿te llega?, ¿a quién vender?, ¿qué cláusula?"""
    adv = price_advice(target)
    price = adv.max_buy
    plan = FinancingPlan(target=target, price=price, budget=budget,
                         affordable_now=budget >= price,
                         shortfall=max(0, price - budget),
                         suggested_clause=adv.suggested_clause)
    if plan.affordable_now:
        plan.budget_after = budget - price
        return plan

    # Hay que vender. Sacrificamos primero lo MENOS valioso (menor score),
    # sin vender al propio objetivo si estuviera (no aplica) y usando su valor de venta.
    candidatos = sorted([s for s in squad if s.player.id != target.player.id],
                        key=lambda s: s.score)
    acumulado = 0
    for s in candidatos:
        if budget + acumulado >= price:
            break
        acumulado += price_advice(s).fair_value   # al vender al sistema recibes el valor
        plan.sells.append(s)

    total_disponible = budget + acumulado
    plan.feasible = total_disponible >= price
    plan.budget_after = total_disponible - price if plan.feasible else total_disponible
    return plan
