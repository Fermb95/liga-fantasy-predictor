"""Bloque 6 — Estado persistente de TU equipo.

Guarda tu plantilla, tu presupuesto y el historial de compras/ventas en SQLite,
de modo que la app recuerda tu situación entre sesiones. Al comprar o vender,
el dinero y la plantilla se actualizan automáticamente.

Módulo puro sobre una conexión sqlite (fácil de testear).
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from . import db

BUDGET_KEY = "budget"


@dataclass
class RosterEntry:
    player_id: int
    purchase_price: int
    clause: int | None
    added_at: str


# ---- Presupuesto ---------------------------------------------------------
def get_budget(conn: sqlite3.Connection) -> int:
    raw = db.get_meta(conn, BUDGET_KEY)
    try:
        return int(raw) if raw is not None else 0
    except ValueError:
        return 0


def set_budget(conn: sqlite3.Connection, value: int) -> None:
    db.set_meta(conn, BUDGET_KEY, str(int(max(0, value))))


# ---- Plantilla -----------------------------------------------------------
def get_roster(conn: sqlite3.Connection) -> list[RosterEntry]:
    return [
        RosterEntry(player_id=r["player_id"], purchase_price=r["purchase_price"],
                    clause=r["clause"], added_at=r["added_at"])
        for r in conn.execute("SELECT * FROM roster ORDER BY added_at")
    ]


def get_roster_ids(conn: sqlite3.Connection) -> set[int]:
    return {r["player_id"] for r in conn.execute("SELECT player_id FROM roster")}


def set_roster(conn: sqlite3.Connection, player_ids, prices: dict[int, int] | None = None) -> None:
    """Fija la plantilla completa (selección manual inicial). No toca el dinero.

    `prices` opcional: {player_id: precio_de_compra}. Si falta, se deja NULL y la
    UI usará el valor de mercado actual como referencia.
    """
    prices = prices or {}
    now = dt.datetime.now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM roster")
    conn.executemany(
        "INSERT INTO roster (player_id, purchase_price, clause, added_at) VALUES (?, ?, ?, ?)",
        [(pid, prices.get(pid), None, now) for pid in player_ids],
    )
    conn.commit()


def _log(conn: sqlite3.Connection, player_id: int, kind: str, price: int) -> None:
    conn.execute(
        "INSERT INTO transactions (player_id, kind, price, ts) VALUES (?, ?, ?, ?)",
        (player_id, kind, int(price), dt.datetime.now().isoformat(timespec="seconds")),
    )


def buy_player(conn: sqlite3.Connection, player_id: int, price: int,
               clause: int | None = None) -> int:
    """Registra una COMPRA: añade a la plantilla, resta del presupuesto, la apunta.

    Devuelve el presupuesto resultante.
    """
    price = int(price)
    now = dt.datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO roster (player_id, purchase_price, clause, added_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(player_id) DO UPDATE SET
             purchase_price=excluded.purchase_price, clause=excluded.clause""",
        (player_id, price, clause, now),
    )
    nuevo = get_budget(conn) - price
    set_budget(conn, nuevo)
    _log(conn, player_id, "buy", price)
    conn.commit()
    return get_budget(conn)


def sell_player(conn: sqlite3.Connection, player_id: int, price: int) -> int:
    """Registra una VENTA: quita de la plantilla, suma al presupuesto, la apunta.

    Devuelve el presupuesto resultante.
    """
    price = int(price)
    conn.execute("DELETE FROM roster WHERE player_id=?", (player_id,))
    set_budget(conn, get_budget(conn) + price)
    _log(conn, player_id, "sell", price)
    conn.commit()
    return get_budget(conn)


def set_clause(conn: sqlite3.Connection, player_id: int, clause: int) -> None:
    conn.execute("UPDATE roster SET clause=? WHERE player_id=?", (int(clause), player_id))
    conn.commit()


def get_transactions(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT player_id, kind, price, ts FROM transactions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- Pujas activas (dinero retenido en el mercado) ----------------------
def add_bid(conn: sqlite3.Connection, player_id: int, amount: int) -> None:
    conn.execute(
        """INSERT INTO bids (player_id, amount, ts) VALUES (?, ?, ?)
           ON CONFLICT(player_id) DO UPDATE SET amount=excluded.amount, ts=excluded.ts""",
        (player_id, int(amount), dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def remove_bid(conn: sqlite3.Connection, player_id: int) -> None:
    conn.execute("DELETE FROM bids WHERE player_id=?", (player_id,))
    conn.commit()


def get_bids(conn: sqlite3.Connection) -> dict[int, int]:
    return {r["player_id"]: r["amount"] for r in conn.execute("SELECT player_id, amount FROM bids")}


# ---- Ventas activas (jugadores tuyos en el mercado) ---------------------
def add_listing(conn: sqlite3.Connection, player_id: int, ask_price: int) -> None:
    conn.execute(
        """INSERT INTO listings (player_id, ask_price, ts) VALUES (?, ?, ?)
           ON CONFLICT(player_id) DO UPDATE SET ask_price=excluded.ask_price, ts=excluded.ts""",
        (player_id, int(ask_price), dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def remove_listing(conn: sqlite3.Connection, player_id: int) -> None:
    conn.execute("DELETE FROM listings WHERE player_id=?", (player_id,))
    conn.commit()


def get_listings(conn: sqlite3.Connection) -> dict[int, int]:
    return {r["player_id"]: r["ask_price"] for r in conn.execute(
        "SELECT player_id, ask_price FROM listings")}


@dataclass
class BudgetView:
    """Modelo de dinero idéntico al de LaLiga Fantasy."""
    valor_plantilla: int     # suma del valor de mercado de tus jugadores + entrenador
    para_gastar: int         # dinero total que te da LaLiga para fichar (X)
    en_pujas: int            # suma de tus pujas activas (se resta del disponible)
    disponible: int          # para_gastar - en_pujas (lo realmente libre ahora)


def export_state(conn: sqlite3.Connection) -> dict:
    """Serializa TU estado (dinero, plantilla, pujas, ventas) a un dict simple,
    para guardarlo fuera de la BD (p. ej. en el navegador)."""
    roster = [[e.player_id, e.purchase_price, e.clause] for e in get_roster(conn)]
    return {
        "budget": get_budget(conn),
        "roster": roster,
        "bids": get_bids(conn),
        "listings": get_listings(conn),
    }


def restore_state(conn: sqlite3.Connection, state: dict) -> None:
    """Reescribe TU estado en la BD a partir de un dict de export_state()."""
    set_budget(conn, int(state.get("budget", 0) or 0))
    roster = state.get("roster", []) or []
    ids = [int(r[0]) for r in roster]
    prices = {int(r[0]): int(r[1]) for r in roster if len(r) > 1 and r[1] is not None}
    set_roster(conn, ids, prices)
    for r in roster:
        if len(r) > 2 and r[2] is not None:
            set_clause(conn, int(r[0]), int(r[2]))
    conn.execute("DELETE FROM bids")
    conn.execute("DELETE FROM listings")
    conn.commit()
    for pid, amt in (state.get("bids") or {}).items():
        add_bid(conn, int(pid), int(amt))
    for pid, ask in (state.get("listings") or {}).items():
        add_listing(conn, int(pid), int(ask))


def is_empty(conn: sqlite3.Connection) -> bool:
    """True si no hay nada de tu estado guardado (plantilla vacía y sin dinero)."""
    return not get_roster_ids(conn) and get_budget(conn) == 0 \
        and not get_bids(conn) and not get_listings(conn)


def budget_view(para_gastar: int, bids: dict[int, int],
                valor_plantilla: int = 0) -> BudgetView:
    """Calcula el desglose de dinero: para gastar, en pujas y disponible."""
    en_pujas = sum(bids.values())
    return BudgetView(
        valor_plantilla=int(valor_plantilla),
        para_gastar=int(para_gastar),
        en_pujas=en_pujas,
        disponible=int(para_gastar) - en_pujas,
    )
