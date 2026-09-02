"""Bloque 3a — Recomendador personal.

Toma los scores del motor (Bloque 2) + tu dinero + tu plantilla y produce
listas ACCIONABLES y acotadas:

  - COMPRAR  : fichajes que puedes pagar y que rinden (no están en tu equipo).
  - VENDER   : jugadores TUYOS que conviene soltar (lesión, bajón, poco valor).
  - MANTENER : jugadores TUYOS que van bien (no toques).
  - IGNORAR  : "trampas" del mercado — nombres caros que NO están rindiendo.

Es un módulo puro (sin BD ni Streamlit) para poder testearlo con datos reales.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from .engine import PlayerScore

MALOS_ESTADOS = ("injured", "suspended", "out_of_league")


@dataclass
class Recommendation:
    comprar: list[PlayerScore] = field(default_factory=list)
    vender: list[PlayerScore] = field(default_factory=list)
    mantener: list[PlayerScore] = field(default_factory=list)
    ignorar: list[PlayerScore] = field(default_factory=list)


def recommend(
    scores: list[PlayerScore],
    budget: float,
    squad_ids: set[int] | list[int] | None = None,
    *,
    max_por_lista: int = 15,
    umbral_comprar: float = 60.0,
    umbral_vender: float = 40.0,
    umbral_trampa: float = 40.0,
) -> Recommendation:
    """Genera la recomendación personalizada.

    - `budget`: dinero disponible en el juego (euros).
    - `squad_ids`: ids de los jugadores que YA tienes.
    """
    squad = set(squad_ids or [])
    rec = Recommendation()

    # Mediana de precio por posición (para detectar "caros que no rinden").
    precios_pos: dict[int, list[int]] = {}
    for s in scores:
        precios_pos.setdefault(s.player.position_id, []).append(s.player.market_value)
    mediana_pos = {pos: median(v) for pos, v in precios_pos.items()}

    for s in scores:
        p = s.player
        en_equipo = p.id in squad

        if en_equipo:
            # Decisión sobre TUS jugadores.
            if p.status in MALOS_ESTADOS or s.signal == "VENDER" or s.score < umbral_vender:
                rec.vender.append(s)
            else:
                rec.mantener.append(s)
            continue

        # Jugadores que NO tienes: candidatos a comprar o trampas a ignorar.
        if p.status in MALOS_ESTADOS:
            continue  # no se compra a un lesionado/sancionado

        asequible = p.market_value <= budget
        if asequible and s.score >= umbral_comprar:
            rec.comprar.append(s)
        elif (s.score < umbral_trampa
              and p.market_value >= mediana_pos.get(p.position_id, 0)):
            # Nombre caro para su posición que no está rindiendo -> ignóralo.
            rec.ignorar.append(s)

    # Orden y recorte para una UI limpia.
    rec.comprar.sort(key=lambda s: s.score, reverse=True)
    rec.vender.sort(key=lambda s: s.score)                       # peores primero
    rec.mantener.sort(key=lambda s: s.score, reverse=True)
    rec.ignorar.sort(key=lambda s: s.player.market_value, reverse=True)  # trampas más caras primero

    rec.comprar = rec.comprar[:max_por_lista]
    rec.ignorar = rec.ignorar[:max_por_lista]
    return rec
