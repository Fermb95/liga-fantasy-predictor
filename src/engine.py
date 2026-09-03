"""Bloque 2 — Motor de valoración.

Convierte los datos crudos (jugadores + calendario) en un *score* 0-100 por
jugador, normalizado dentro de su posición, más sub-métricas explicables y una
señal de mercado genérica (CHOLLO / MANTENER / VENDER).

Es un módulo PURO: recibe listas de `Player`/`Fixture` y devuelve resultados;
no toca la BD ni la red, por lo que es fácil de testear con datos sintéticos.
La recomendación PERSONAL (según tu dinero y tu plantilla) es el Bloque 3.

Señales:
  1. Rentabilidad    -> puntos por millón de € (lo barato que rinde).
  2. Forma reciente  -> media ponderada de las últimas jornadas jugadas.
  3. Titularidad     -> fracción de jornadas jugadas en las que puntuó (>0).
  4. Calendario      -> facilidad de los próximos rivales (rival débil = bonus).
  5. Estado (mult.)  -> penaliza lesionado/sancionado/duda/fuera de liga.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .api_client import Fixture, Player

MATCH_FINISHED = 7

# Factor multiplicador según disponibilidad del jugador.
STATUS_FACTOR = {
    "ok": 1.0,
    "doubtful": 0.6,
    "injured": 0.15,
    "suspended": 0.15,
    "out_of_league": 0.0,
}


@dataclass
class Weights:
    """Pesos de las señales (base). Ajustables por el usuario."""
    rentabilidad: float = 0.30
    forma: float = 0.30
    titularidad: float = 0.20
    calendario: float = 0.20

    def total(self) -> float:
        return self.rentabilidad + self.forma + self.titularidad + self.calendario


@dataclass
class PlayerScore:
    player: Player
    score: float                 # 0-100, normalizado dentro de la posición
    signal: str                  # CHOLLO / MANTENER / VENDER
    rentabilidad: float          # puntos por millón (bruto, interpretable)
    forma: float                 # media ponderada últimas jornadas
    titularidad: float           # 0-1
    facilidad_calendario: float  # 0-1 (1 = rivales fáciles)
    metrics: dict = field(default_factory=dict)  # normalizados usados en el score


# ---- Métricas base -------------------------------------------------------
def recent_form(week_points: dict[int, int], n: int = 3) -> float:
    """Media ponderada de las últimas `n` jornadas jugadas (más reciente pesa más)."""
    if not week_points:
        return 0.0
    ultimas = sorted(week_points.items(), key=lambda kv: kv[0])[-n:]
    # Pesos crecientes hacia la jornada más reciente: p.ej. [1,2,3].
    pesos = list(range(1, len(ultimas) + 1))
    num = sum(p * pts for p, (_, pts) in zip(pesos, ultimas))
    return num / sum(pesos)


def titularidad(week_points: dict[int, int]) -> float:
    """Fracción de jornadas jugadas en las que el jugador puntuó (>0)."""
    if not week_points:
        return 0.0
    jugadas = len(week_points)
    puntuadas = sum(1 for v in week_points.values() if v > 0)
    return puntuadas / jugadas


def rentabilidad(points: int, market_value: int) -> float:
    """Puntos por millón de euros. 0 si no hay valor de mercado."""
    if market_value <= 0:
        return 0.0
    return points / (market_value / 1_000_000)


def team_strength(fixtures: list[Fixture]) -> dict[int, float]:
    """Fuerza de cada equipo (0-1) a partir de los partidos ya jugados.

    Usa puntos de liga (victoria=3, empate=1) sobre los partidos finalizados y
    los normaliza min-max. Si no hay partidos jugados, todos valen 0.5.
    """
    pts: dict[int, int] = {}
    jugados: dict[int, int] = {}
    for f in fixtures:
        if f.match_state != MATCH_FINISHED or f.local_score is None or f.visitor_score is None:
            continue
        for t in (f.local_id, f.visitor_id):
            pts.setdefault(t, 0)
            jugados.setdefault(t, 0)
            jugados[t] += 1
        if f.local_score > f.visitor_score:
            pts[f.local_id] += 3
        elif f.local_score < f.visitor_score:
            pts[f.visitor_id] += 3
        else:
            pts[f.local_id] += 1
            pts[f.visitor_id] += 1
    if not pts:
        return {}
    # Puntos por partido (evita penalizar a quien ha jugado menos partidos).
    ppp = {t: pts[t] / jugados[t] for t in pts}
    return _minmax_map(ppp, default=0.5)


def upcoming_ease(team_id: int, fixtures: list[Fixture], strength: dict[int, float],
                  n: int = 3, home_bonus: float = 0.05) -> float:
    """Facilidad (0-1) de los próximos `n` partidos del equipo: rival débil = fácil."""
    prox = [f for f in fixtures if f.match_state != MATCH_FINISHED
            and team_id in (f.local_id, f.visitor_id)]
    prox.sort(key=lambda f: (f.week, f.date))
    prox = prox[:n]
    if not prox:
        return 0.5
    vals = []
    for f in prox:
        rival = f.visitor_id if f.local_id == team_id else f.local_id
        es_local = f.local_id == team_id
        facilidad = 1.0 - strength.get(rival, 0.5)  # rival fuerte -> difícil
        facilidad += home_bonus if es_local else 0.0
        vals.append(max(0.0, min(1.0, facilidad)))
    return sum(vals) / len(vals)


def next_opponents(team_id: int, fixtures: list[Fixture], n: int = 1) -> list[tuple[int, bool, int]]:
    """Próximos rivales del equipo: lista de (rival_id, es_local, jornada)."""
    prox = [f for f in fixtures if f.match_state != MATCH_FINISHED
            and team_id in (f.local_id, f.visitor_id)]
    prox.sort(key=lambda f: (f.week, f.date))
    out = []
    for f in prox[:n]:
        rival = f.visitor_id if f.local_id == team_id else f.local_id
        out.append((rival, f.local_id == team_id, f.week))
    return out


# ---- Utilidades de normalización ----------------------------------------
def _minmax_map(values: dict[int, float], default: float = 0.5) -> dict[int, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: default for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def _minmax_list(values: list[float], default: float = 0.5) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [default] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


# ---- Score compuesto -----------------------------------------------------
def score_players(players: list[Player], fixtures: list[Fixture],
                  weights: Weights | None = None) -> list[PlayerScore]:
    """Calcula el score 0-100 de cada jugador, normalizado dentro de su posición."""
    weights = weights or Weights()
    strength = team_strength(fixtures)

    # 1) Métricas brutas por jugador.
    brutos = []
    for p in players:
        brutos.append({
            "p": p,
            "rent": rentabilidad(p.points, p.market_value),
            "forma": recent_form(p.week_points),
            "titu": titularidad(p.week_points),
            "cal": upcoming_ease(p.team_id, fixtures, strength),
        })

    # 2) Normalización de sub-métricas DENTRO de cada posición.
    por_pos: dict[int, list[dict]] = {}
    for b in brutos:
        por_pos.setdefault(b["p"].position_id, []).append(b)

    resultados: list[PlayerScore] = []
    for pos, grupo in por_pos.items():
        n_rent = _minmax_list([g["rent"] for g in grupo])
        n_forma = _minmax_list([g["forma"] for g in grupo])
        n_titu = _minmax_list([g["titu"] for g in grupo])
        n_cal = _minmax_list([g["cal"] for g in grupo])

        finales = []
        for g, r, f, t, c in zip(grupo, n_rent, n_forma, n_titu, n_cal):
            base = (weights.rentabilidad * r + weights.forma * f
                    + weights.titularidad * t + weights.calendario * c) / weights.total()
            final = base * STATUS_FACTOR.get(g["p"].status, 1.0)
            finales.append(final)
            g["_norm"] = {"rent": r, "forma": f, "titu": t, "cal": c, "base": base}

        # 3) Escalado final a 0-100 dentro de la posición.
        escala = _minmax_list(finales, default=0.5)
        for g, esc in zip(grupo, escala):
            p = g["p"]
            resultados.append(PlayerScore(
                player=p,
                score=round(esc * 100, 1),
                signal="",  # se rellena tras conocer todos los scores
                rentabilidad=round(g["rent"], 2),
                forma=round(g["forma"], 2),
                titularidad=round(g["titu"], 2),
                facilidad_calendario=round(g["cal"], 2),
                metrics=g["_norm"],
            ))

    # 4) Señal de mercado genérica (independiente de tu plantilla).
    _assign_signals(resultados)
    resultados.sort(key=lambda r: r.score, reverse=True)
    return resultados


def _assign_signals(scores: list[PlayerScore]) -> None:
    """Etiqueta CHOLLO / MANTENER / VENDER según score y estado, por posición."""
    por_pos: dict[int, list[PlayerScore]] = {}
    for s in scores:
        por_pos.setdefault(s.player.position_id, []).append(s)
    for grupo in por_pos.values():
        for s in grupo:
            st = s.player.status
            if st in ("injured", "suspended", "out_of_league"):
                s.signal = "VENDER"
            elif s.score >= 65 and st == "ok":
                s.signal = "CHOLLO"
            elif s.score <= 30:
                s.signal = "VENDER" if s.forma < 2 else "MANTENER"
            else:
                s.signal = "MANTENER"
