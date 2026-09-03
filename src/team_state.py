"""Estado del equipo de CADA usuario: plantilla, presupuesto, pujas y ventas.

Todas las funciones reciben `user_id`, de modo que cada persona tiene su propio
equipo aunque compartan la misma base de datos (Turso). Módulo puro sobre una
conexión (SQLite local o Turso).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from . import db


@dataclass
class RosterEntry:
    player_id: int
    purchase_price: int
    clause: int | None
    added_at: str


# ---- Presupuesto (dinero para gastar) -----------------------------------
def get_budget(conn, user_id: int) -> int:
    row = conn.execute("SELECT amount FROM budgets WHERE user_id=?", (user_id,)).fetchone()
    return int(row["amount"]) if row else 0


def set_budget(conn, user_id: int, value: int) -> None:
    value = int(max(0, value))
    conn.execute(
        "INSERT INTO budgets (user_id, amount) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET amount=excluded.amount",
        (user_id, value),
    )
    conn.commit()


# ---- Plantilla -----------------------------------------------------------
def get_roster(conn, user_id: int) -> list[RosterEntry]:
    return [
        RosterEntry(player_id=r["player_id"], purchase_price=r["purchase_price"],
                    clause=r["clause"], added_at=r["added_at"])
        for r in conn.execute(
            "SELECT * FROM roster WHERE user_id=? ORDER BY added_at", (user_id,))
    ]


def get_roster_ids(conn, user_id: int) -> set[int]:
    return {r["player_id"] for r in conn.execute(
        "SELECT player_id FROM roster WHERE user_id=?", (user_id,))}


def set_roster(conn, user_id: int, player_ids, prices: dict[int, int] | None = None) -> None:
    prices = prices or {}
    now = dt.datetime.now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM roster WHERE user_id=?", (user_id,))
    conn.executemany(
        "INSERT INTO roster (user_id, player_id, purchase_price, clause, added_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [(user_id, pid, prices.get(pid), None, now) for pid in player_ids],
    )
    conn.commit()


def _log(conn, user_id: int, player_id: int, kind: str, price: int) -> None:
    conn.execute(
        "INSERT INTO transactions (user_id, player_id, kind, price, ts) VALUES (?, ?, ?, ?, ?)",
        (user_id, player_id, kind, int(price), dt.datetime.now().isoformat(timespec="seconds")),
    )


def buy_player(conn, user_id: int, player_id: int, price: int, clause: int | None = None) -> int:
    price = int(price)
    now = dt.datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO roster (user_id, player_id, purchase_price, clause, added_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id, player_id) DO UPDATE SET "
        "purchase_price=excluded.purchase_price, clause=excluded.clause",
        (user_id, player_id, price, clause, now),
    )
    set_budget(conn, user_id, get_budget(conn, user_id) - price)
    _log(conn, user_id, player_id, "buy", price)
    conn.commit()
    return get_budget(conn, user_id)


def sell_player(conn, user_id: int, player_id: int, price: int) -> int:
    price = int(price)
    conn.execute("DELETE FROM roster WHERE user_id=? AND player_id=?", (user_id, player_id))
    set_budget(conn, user_id, get_budget(conn, user_id) + price)
    _log(conn, user_id, player_id, "sell", price)
    conn.commit()
    return get_budget(conn, user_id)


def set_clause(conn, user_id: int, player_id: int, clause: int) -> None:
    conn.execute("UPDATE roster SET clause=? WHERE user_id=? AND player_id=?",
                 (int(clause), user_id, player_id))
    conn.commit()


def get_transactions(conn, user_id: int, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT player_id, kind, price, ts FROM transactions WHERE user_id=? "
        "ORDER BY id DESC LIMIT ?", (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- Pujas activas -------------------------------------------------------
def add_bid(conn, user_id: int, player_id: int, amount: int) -> None:
    conn.execute(
        "INSERT INTO bids (user_id, player_id, amount, ts) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, player_id) DO UPDATE SET amount=excluded.amount, ts=excluded.ts",
        (user_id, player_id, int(amount), dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def remove_bid(conn, user_id: int, player_id: int) -> None:
    conn.execute("DELETE FROM bids WHERE user_id=? AND player_id=?", (user_id, player_id))
    conn.commit()


def get_bids(conn, user_id: int) -> dict[int, int]:
    return {r["player_id"]: r["amount"] for r in conn.execute(
        "SELECT player_id, amount FROM bids WHERE user_id=?", (user_id,))}


# ---- Ventas activas ------------------------------------------------------
def add_listing(conn, user_id: int, player_id: int, ask_price: int) -> None:
    conn.execute(
        "INSERT INTO listings (user_id, player_id, ask_price, ts) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, player_id) DO UPDATE SET ask_price=excluded.ask_price, ts=excluded.ts",
        (user_id, player_id, int(ask_price), dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def remove_listing(conn, user_id: int, player_id: int) -> None:
    conn.execute("DELETE FROM listings WHERE user_id=? AND player_id=?", (user_id, player_id))
    conn.commit()


def get_listings(conn, user_id: int) -> dict[int, int]:
    return {r["player_id"]: r["ask_price"] for r in conn.execute(
        "SELECT player_id, ask_price FROM listings WHERE user_id=?", (user_id,))}


# ---- Importar / exportar / vacío ----------------------------------------
def export_state(conn, user_id: int) -> dict:
    roster = [[e.player_id, e.purchase_price, e.clause] for e in get_roster(conn, user_id)]
    return {"budget": get_budget(conn, user_id), "roster": roster,
            "bids": get_bids(conn, user_id), "listings": get_listings(conn, user_id)}


def restore_state(conn, user_id: int, state: dict) -> None:
    set_budget(conn, user_id, int(state.get("budget", 0) or 0))
    roster = state.get("roster", []) or []
    ids = [int(r[0]) for r in roster]
    prices = {int(r[0]): int(r[1]) for r in roster if len(r) > 1 and r[1] is not None}
    set_roster(conn, user_id, ids, prices)
    for r in roster:
        if len(r) > 2 and r[2] is not None:
            set_clause(conn, user_id, int(r[0]), int(r[2]))
    conn.execute("DELETE FROM bids WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM listings WHERE user_id=?", (user_id,))
    conn.commit()
    for pid, amt in (state.get("bids") or {}).items():
        add_bid(conn, user_id, int(pid), int(amt))
    for pid, ask in (state.get("listings") or {}).items():
        add_listing(conn, user_id, int(pid), int(ask))


def is_empty(conn, user_id: int) -> bool:
    return not get_roster_ids(conn, user_id) and get_budget(conn, user_id) == 0 \
        and not get_bids(conn, user_id) and not get_listings(conn, user_id)


# ---- Vista de dinero (pura) ---------------------------------------------
@dataclass
class BudgetView:
    valor_plantilla: int
    para_gastar: int
    en_pujas: int
    disponible: int


def budget_view(para_gastar: int, bids: dict[int, int], valor_plantilla: int = 0) -> BudgetView:
    en_pujas = sum(bids.values())
    return BudgetView(valor_plantilla=int(valor_plantilla), para_gastar=int(para_gastar),
                      en_pujas=en_pujas, disponible=int(para_gastar) - en_pujas)
