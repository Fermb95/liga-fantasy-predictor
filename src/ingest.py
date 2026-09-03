"""Orquestador de ingesta: API pública -> SQLite. Ejecutar tras cada jornada."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import db
from .api_client import FantasyClient


def _log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def run_ingest(db_path: str | Path = db.DEFAULT_DB, client: FantasyClient | None = None) -> dict[str, int]:
    """Descarga jugadores, equipos y calendario y los vuelca en SQLite/Turso.

    Imprime progreso (útil para ver dónde tarda en GitHub Actions).
    """
    client = client or FantasyClient()
    _log(f"Conectando a la base de datos ({'Turso' if db.using_turso() else 'SQLite local'})...")
    conn = db.connect(db_path)
    try:
        _log("Descargando equipos...")
        teams = client.get_teams_from_week(1)
        n_teams = db.upsert_teams(conn, teams)
        _log(f"  equipos: {n_teams}")

        _log("Descargando jugadores...")
        players = client.get_players()
        _log(f"  jugadores descargados: {len(players)}. Guardando...")
        n_players = db.upsert_players(conn, players)
        _log("  jugadores guardados.")

        _log("Descargando calendario (jornadas 1-38)...")
        fixtures = client.get_all_fixtures()
        _log(f"  partidos: {len(fixtures)}. Guardando...")
        n_fixtures = db.upsert_fixtures(conn, fixtures)
        _log("  calendario guardado.")

        _log("Guardando snapshot de valores (tendencias)...")
        db.record_values(conn, players)

        db.set_meta(conn, "last_ingest", dt.datetime.now().isoformat(timespec="seconds"))
        _log("OK: ingesta completada.")
        return {"teams": n_teams, "players": n_players, "fixtures": n_fixtures}
    finally:
        conn.close()


if __name__ == "__main__":
    summary = run_ingest()
    print("Ingesta completada:")
    for k, v in summary.items():
        print(f"  {k}: {v}")
