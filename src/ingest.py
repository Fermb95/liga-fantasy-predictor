"""Orquestador de ingesta: API pública -> SQLite. Ejecutar tras cada jornada."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import db
from .api_client import FantasyClient


def run_ingest(db_path: str | Path = db.DEFAULT_DB, client: FantasyClient | None = None) -> dict[str, int]:
    """Descarga jugadores, equipos y calendario y los vuelca en SQLite.

    Devuelve un resumen con el número de filas insertadas/actualizadas.
    """
    client = client or FantasyClient()
    conn = db.connect(db_path)
    try:
        db.init_db(conn)

        teams = client.get_teams_from_week(1)
        n_teams = db.upsert_teams(conn, teams)

        players = client.get_players()
        n_players = db.upsert_players(conn, players)

        fixtures = client.get_all_fixtures()
        n_fixtures = db.upsert_fixtures(conn, fixtures)

        db.set_meta(conn, "last_ingest", dt.datetime.now().isoformat(timespec="seconds"))

        return {"teams": n_teams, "players": n_players, "fixtures": n_fixtures}
    finally:
        conn.close()


if __name__ == "__main__":
    summary = run_ingest()
    print("Ingesta completada:")
    for k, v in summary.items():
        print(f"  {k}: {v}")
