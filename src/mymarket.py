"""Análisis de "mi mercado": ranking de prioridad de compra.

Dado los jugadores que te salen en el mercado ahora, tu plantilla y tu dinero,
ordena por prioridad de fichaje teniendo en cuenta: rendimiento (score), encaje
en tu equipo (lo que te hace falta reforzar), si te llega el dinero (con o sin
vender), la tendencia de su valor, tus PUJAS activas y lo que tienes A LA VENTA.

Lo que tienes a la venta importa por dos motivos:
  - Si lo vendes, tienes MÁS dinero para pujar (se suma al disponible).
  - Sirve de referencia: si un jugador del mercado es peor que el que estás
    vendiendo en esa posición, no tiene sentido ficharlo (mejor quédate el tuyo).
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
    note: str = ""                  # aviso (pujas / ventas: ver más abajo)
    upgrades_listing: bool = False  # mejora a un jugador que tienes en venta


@dataclass
class ListingReview:
    """Veredicto sobre un jugador que tienes A LA VENTA: ¿vender o quedárselo?"""
    ps: PlayerScore
    ask_price: int
    verdict: str                     # 🔁 Vender y fichar mejor / 🔒 Quédatelo
    better: list[PlayerScore]        # opciones del mercado mejores que él (y asequibles)
    note: str


# Diferencia mínima de score para considerar "claramente mejor" (evita empates).
_MEJOR_MARGEN = 5.0


def rank_market(market_scores: list[PlayerScore], squad_scores: list[PlayerScore],
                disponible: int, trend_map: dict | None = None,
                bids: dict | None = None, listings: dict | None = None) -> list[MarketPick]:
    """Ordena por prioridad de compra teniendo en cuenta rendimiento, encaje en tu
    plantilla, calendario, precio, tendencia, tus PUJAS activas y tus VENTAS.

    `bids`: {player_id: (PlayerScore, importe)} de los jugadores por los que ya
    estás pujando. Se usa para marcarlos y para no recomendar fichar a un peor de
    la misma posición por la que ya vas a por uno mejor.

    `listings`: {player_id: (PlayerScore, precio_venta)} de los jugadores que
    tienes a la venta. Su precio se suma al dinero disponible (si los vendes tienes
    más para pujar) y sirven de referencia: si el del mercado es peor que el que
    vendes, se avisa (mejor quédate el tuyo).
    """
    trend_map = trend_map or {}
    bids = bids or {}
    listings = listings or {}
    squad_ids = {s.player.id for s in squad_scores}
    bidding_ids = set(bids)

    # Dinero que tendrías si vendes TODO lo que tienes listado a la venta.
    liquidez_ventas = sum(int(ask) for _ls, ask in listings.values())
    disponible_venta = disponible + liquidez_ventas

    # Mejor puja pendiente por posición (para no fichar un peor en esa línea).
    best_bid_pos: dict[int, PlayerScore] = {}
    for bs, _amt in bids.values():
        pos = bs.player.position_id
        if pos not in best_bid_pos or bs.score > best_bid_pos[pos].score:
            best_bid_pos[pos] = bs

    # Mejor jugador que tienes A LA VENTA por posición (referencia de reemplazo).
    best_listing_pos: dict[int, PlayerScore] = {}
    for ls, _ask in listings.values():
        pos = ls.player.position_id
        if pos not in best_listing_pos or ls.score > best_listing_pos[pos].score:
            best_listing_pos[pos] = ls

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
        elif disponible_venta >= adv.max_buy:
            afford = "vendiendo"          # te llega si vendes lo que tienes listado
        else:
            plan = advisor.bid_plan(s, adv.max_buy, disponible_venta, squad_scores)
            afford = "vendiendo" if plan.feasible else "no_te_llega"

        t = trend_map.get(pid)
        trend_dir = t.direction if t else "new"
        trend_bonus = 4 if trend_dir == "up" else (-4 if trend_dir == "down" else 0)
        priority = s.score * FIT_FACTOR.get(fit, 1.0) * AFFORD_FACTOR.get(afford, 0.5) + trend_bonus

        note = ""
        espera = False
        hold_listing = False
        upgrades_listing = False
        if not already:
            mejor = best_bid_pos.get(s.player.position_id)
            if mejor and mejor.player.id != pid and mejor.score > s.score + _MEJOR_MARGEN:
                # Ya vas a por uno mejor en esa posición: no tiene sentido fichar este.
                priority *= 0.45
                note = f"Ya pujas por {mejor.player.nickname} (mejor) en esa posición"
                espera = True
            else:
                # Compara con lo que tienes a la venta en su misma posición.
                en_venta = best_listing_pos.get(s.player.position_id)
                if en_venta and en_venta.player.id != pid:
                    if en_venta.score > s.score + _MEJOR_MARGEN:
                        # Vendes uno mejor que este: mejor quédate el tuyo.
                        priority *= 0.55
                        note = (f"Tu {en_venta.player.nickname} (en venta) es mejor; "
                                f"plantéate no venderlo")
                        hold_listing = True
                    elif s.score > en_venta.score + _MEJOR_MARGEN:
                        # Mejora a uno que ya vendes: reemplazo con sentido.
                        priority *= 1.1
                        upgrades_listing = True
                        note = f"Mejora a {en_venta.player.nickname}, que tienes en venta"

        priority = round(priority, 1)
        if s.player.status in ("injured", "suspended", "out_of_league"):
            verdict = "🔴 Lesionado/sancionado"
        elif already:
            verdict = "📌 Pujando"
        elif espera:
            verdict = "🟡 Espera"
        elif hold_listing:
            verdict = "🟡 Mejor quédate el tuyo"
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
            bid_amount=int(bids[pid][1]) if already else 0, note=note,
            upgrades_listing=upgrades_listing))

    picks.sort(key=lambda p: p.priority, reverse=True)
    return picks


def review_listings(listings: dict, market_scores: list[PlayerScore],
                    disponible: int) -> list[ListingReview]:
    """Para cada jugador que tienes A LA VENTA, dice si merece la pena venderlo.

    `listings`: {player_id: (PlayerScore, precio_venta)}.

    Merece venderlo si en tu mercado hay algún jugador de su misma posición
    claramente mejor y que podrías pagar con lo que sacarías (disponible + su
    precio de venta). Si no hay nada mejor, mejor quédatelo (salvo que necesites
    hueco o liquidez).
    """
    reviews: list[ListingReview] = []
    for pid, (ls, ask) in listings.items():
        pos = ls.player.position_id
        presupuesto = disponible + int(ask)   # lo que tendrías para reemplazarlo
        better: list[PlayerScore] = []
        for m in market_scores:
            if m.player.id == pid or m.player.position_id != pos:
                continue
            if m.player.status in ("injured", "suspended", "out_of_league"):
                continue
            if m.score <= ls.score + _MEJOR_MARGEN:
                continue
            if market.price_advice(m).max_buy <= presupuesto:
                better.append(m)
        better.sort(key=lambda x: x.score, reverse=True)
        if better:
            verdict = "🔁 Vender y fichar mejor"
            note = ("hay mejores en tu mercado por lo que sacarías: "
                    + ", ".join(b.player.nickname for b in better[:3]))
        else:
            verdict = "🔒 Quédatelo"
            note = ("nada de tu mercado lo mejora por ese precio; "
                    "véndelo solo si necesitas hueco o liquidez")
        reviews.append(ListingReview(ps=ls, ask_price=int(ask), verdict=verdict,
                                     better=better, note=note))
    return reviews
