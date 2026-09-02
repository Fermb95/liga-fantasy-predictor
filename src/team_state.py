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
    disponible: int          # dinero libre ahora (lo que muestra LaLiga)
    comprometido_pujas: int  # dinero retenido en pujas activas
    si_fallan_pujas: int     # disponible + pujas (si te las devuelven)
    en_venta_pedido: int     # suma de precios que pides por lo que tienes en venta
    en_venta_mercado: int    # suma del valor de mercado de lo que tienes en venta
    si_vendo_pedido: int     # disponible + lo que pides por tus ventas
    si_vendo_mercado: int    # disponible + valor de mercado de tus ventas (más realista)


def budget_view(disponible: int, bids: dict[int, int], listings: dict[int, int],
                market_value_by_id: dict[int, int]) -> BudgetView:
    """Calcula los distintos 'presupuestos' según pujas y ventas activas."""
    comprometido = sum(bids.values())
    pedido = sum(listings.values())
    mercado = sum(market_value_by_id.get(pid, 0) for pid in listings)
    return BudgetView(
        disponible=disponible,
        comprometido_pujas=comprometido,
        si_fallan_pujas=disponible + comprometido,
        en_venta_pedido=pedido,
        en_venta_mercado=mercado,
        si_vendo_pedido=disponible + pedido,
        si_vendo_mercado=disponible + mercado,
    )
