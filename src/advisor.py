"""Bloque 11 — Asesor de puja y venta, con encaje en el equipo.

Responde a las decisiones del día a día:
  - VENTA: si tienes un jugador en venta, ¿cuál es un buen precio y cuál es el
    mínimo que deberías aceptar? (nunca por debajo de su valor de mercado, porque
    a ese precio te lo compra el sistema).
  - PUJA: para un jugador de tu mercado, ¿es chollo o paso?, ¿hasta cuánto pujar?,
    ¿te encaja en el equipo o ya vas sobrado en esa posición?
  - SUSTITUCIÓN: si pujas por él, ¿a quién desplaza?, ¿conviene venderlo?, ¿cuánto
    dinero te quedaría?, ¿necesitas vender a alguien más para pagarlo?

Módulo puro sobre PlayerScore (de engine.score_players).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import market
from .engine import PlayerScore

# Titulares típicos por posición (para juzgar si un fichaje aporta o es suplente).
STARTERS_BY_POS = {1: 1, 2: 4, 3: 4, 4: 2}  # POR, DEF, MED, DEL
POS_NOMBRE = {1: "Portería", 2: "Defensa", 3: "Medio", 4: "Delantera"}


@dataclass
class PositionStat:
    position_id: int
    count: int            # cuántos tienes en esa posición
    need: int             # titulares típicos
    avg_starters: float   # score medio de tus mejores (los que serían titulares)
    level: str            # 🔴 falta fondo / 🟠 floja / 🟡 correcta / 🟢 fuerte


def position_summary(squad_scores: list[PlayerScore]) -> list[PositionStat]:
    """Fuerza de tu plantilla por posición: dónde vas sobrado y dónde reforzar."""
    por_pos: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}
    for s in squad_scores:
        if s.player.position_id in por_pos:
            por_pos[s.player.position_id].append(s.score)
    out: list[PositionStat] = []
    for pos in (1, 2, 3, 4):
        vals = sorted(por_pos[pos], reverse=True)
        need = STARTERS_BY_POS[pos]
        count = len(vals)
        titulares = vals[:need]
        avg = round(sum(titulares) / len(titulares), 1) if titulares else 0.0
        if count < need:
            level = "🔴 falta fondo"
        elif avg < 45:
            level = "🟠 floja"
        elif avg < 65:
            level = "🟡 correcta"
        else:
            level = "🟢 fuerte"
        out.append(PositionStat(pos, count, need, avg, level))
    return out


def refuerzos_sugeridos(squad_scores: list[PlayerScore]) -> list[int]:
    """Ids de posición donde conviene reforzar (falta fondo o línea floja)."""
    return [p.position_id for p in position_summary(squad_scores)
            if p.level in ("🔴 falta fondo", "🟠 floja")]


# ---- Venta ---------------------------------------------------------------
@dataclass
class SellAdvice:
    good_price: int     # buen precio de venta (con prima si el jugador es bueno)
    min_accept: int     # mínimo a aceptar (su valor de mercado: el sistema paga eso)


def sell_advice(ps: PlayerScore) -> SellAdvice:
    adv = market.price_advice(ps)
    # Nunca aceptes menos que el valor de mercado: a ese precio lo vende el sistema.
    return SellAdvice(good_price=max(adv.sell_ask, adv.fair_value),
                      min_accept=adv.fair_value)


# ---- Encaje en el equipo -------------------------------------------------
def team_fit(target: PlayerScore, squad: list[PlayerScore]) -> tuple[str, str]:
    """Devuelve (etiqueta, motivo): ENCAJA / MEJORA / NO_ENCAJA."""
    pos = target.player.position_id
    same = sorted([s for s in squad if s.player.position_id == pos],
                  key=lambda s: s.score, reverse=True)
    need = STARTERS_BY_POS.get(pos, 3)
    nombre_pos = {1: "portería", 2: "defensa", 3: "medio", 4: "delantera"}.get(pos, "esa posición")
    if len(same) < need:
        return "ENCAJA", f"te falta fondo en {nombre_pos} (tienes {len(same)})"
    peor_titular = same[need - 1]
    if target.score > peor_titular.score:
        return "MEJORA", f"mejor que tu {peor_titular.player.nickname} (score {peor_titular.score})"
    return "NO_ENCAJA", (f"ya tienes {need} mejores en {nombre_pos}; "
                         f"sería suplente (tu peor titular ahí marca {peor_titular.score})")


# ---- Puja + sustitución + financiación -----------------------------------
@dataclass
class BidPlan:
    target: PlayerScore
    bid: int
    disponible: int
    max_recomendada: int                  # puja máxima aconsejada
    fit: str                              # ENCAJA / MEJORA / NO_ENCAJA
    fit_reason: str
    cash_after_bid: int                   # dinero tras la compra (si no vendes nada)
    substitute_out: PlayerScore | None    # a quién desplaza (más flojo de su puesto)
    sell_substitute: bool                 # ¿conviene venderlo?
    cash_if_sell_substitute: int          # dinero si vendes al desplazado
    extra_sells: list[PlayerScore] = field(default_factory=list)  # ventas extra si falta
    cash_final: int = 0
    feasible: bool = True


def bid_plan(target: PlayerScore, bid: int, disponible: int,
             squad: list[PlayerScore]) -> BidPlan:
    adv = market.price_advice(target)
    fit, reason = team_fit(target, squad)
    pos = target.player.position_id
    same = [s for s in squad if s.player.position_id == pos]
    substitute = min(same, key=lambda s: s.score) if same else None

    cash_after_bid = disponible - bid
    # Conviene vender al desplazado si ya vas cubierto en la posición (no lo
    # necesitas de fondo) o si necesitas dinero.
    sell_sub = substitute is not None and (fit != "ENCAJA" or cash_after_bid < 0)
    cash_if_sell = cash_after_bid + (sell_advice(substitute).min_accept if (substitute and sell_sub) else 0)

    plan = BidPlan(
        target=target, bid=bid, disponible=disponible, max_recomendada=adv.max_buy,
        fit=fit, fit_reason=reason, cash_after_bid=cash_after_bid,
        substitute_out=substitute, sell_substitute=sell_sub,
        cash_if_sell_substitute=cash_if_sell,
    )

    # Dinero de partida tras (opcionalmente) vender al desplazado.
    cash = cash_if_sell if sell_sub else cash_after_bid
    ya_vendidos = {substitute.player.id} if (substitute and sell_sub) else set()

    # Si aún falta dinero, vende lo menos valioso hasta cubrir.
    if cash < 0:
        candidatos = sorted([s for s in squad if s.player.id not in ya_vendidos
                             and s.player.id != target.player.id],
                            key=lambda s: s.score)
        for s in candidatos:
            if cash >= 0:
                break
            cash += sell_advice(s).min_accept
            plan.extra_sells.append(s)

    plan.cash_final = cash
    plan.feasible = cash >= 0
    return plan
