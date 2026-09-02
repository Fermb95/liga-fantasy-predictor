"""Tests reales contra la API pública de LaLiga Fantasy (marcados como 'live')."""
import pytest

from src.api_client import FantasyClient, Fixture, Player, Team


@pytest.fixture(scope="module")
def client():
    return FantasyClient()


@pytest.mark.live
def test_get_players_devuelve_catalogo_completo(client):
    players = client.get_players()
    assert isinstance(players, list)
    assert len(players) > 500  # ~835 jugadores en la temporada
    p = players[0]
    assert isinstance(p, Player)
    assert p.id > 0
    assert p.nickname
    assert p.market_value > 0
    assert p.position in {"Portero", "Defensa", "Centrocampista", "Delantero", "Entrenador"}


@pytest.mark.live
def test_players_tienen_week_points_y_status(client):
    players = client.get_players()
    # Al menos algún jugador con puntos por jornada y con estado conocido.
    assert any(p.week_points for p in players)
    estados = {p.status for p in players}
    assert "ok" in estados


@pytest.mark.live
def test_get_teams_from_week(client):
    teams = client.get_teams_from_week(1)
    assert len(teams) == 20  # 10 partidos por jornada -> 20 equipos
    t = teams[0]
    assert isinstance(t, Team)
    assert t.name


@pytest.mark.live
def test_get_week_stats(client):
    fixtures = client.get_week_stats(1)
    assert len(fixtures) == 10  # 10 partidos por jornada
    f = fixtures[0]
    assert isinstance(f, Fixture)
    assert f.week == 1
    assert f.local_id > 0 and f.visitor_id > 0


@pytest.mark.live
def test_teamid_de_jugador_coincide_con_equipos(client):
    """El teamId del jugador debe existir entre los equipos derivados de los partidos."""
    teams = {t.id for t in client.get_teams_from_week(1)}
    players = client.get_players()
    # La gran mayoría de jugadores 'ok' pertenecen a un equipo de la competición.
    activos = [p for p in players if p.status == "ok"]
    con_equipo = [p for p in activos if p.team_id in teams]
    assert len(con_equipo) / len(activos) > 0.9
