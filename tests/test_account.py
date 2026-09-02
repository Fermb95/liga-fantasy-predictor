"""Tests del cliente autenticado (Bloque 4). Parseo con respuestas simuladas."""
import os

import pytest

from src import account, auth


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


class FakeSession:
    """Session falsa que devuelve respuestas según un mapa {fragmento_url: payload}."""
    def __init__(self, rutas):
        self.rutas = rutas
        self.headers = {}

    def get(self, url, params=None, headers=None, timeout=None):
        for frag, payload in self.rutas.items():
            if frag in url:
                return FakeResp(200, payload)
        return FakeResp(404, {})


def make_client(rutas):
    c = account.AccountClient(token="fake-token")
    c._session = FakeSession(rutas)
    return c


def test_get_leagues_parsea_team_y_dinero():
    payload = [{
        "id": "L1", "name": "Liga de amigos", "managersNumber": 8,
        "team": {"id": 555, "money": 3_500_000, "teamPoints": 120},
    }]
    c = make_client({"/leagues": payload})
    ligas = c.get_leagues()
    assert len(ligas) == 1
    assert ligas[0].team_id == 555
    assert ligas[0].money == 3_500_000
    assert ligas[0].name == "Liga de amigos"


def test_get_leagues_acepta_lista_envuelta():
    payload = {"leagues": [{"id": "L2", "name": "Otra", "managersNumber": 5,
                            "team": {"id": 9, "money": 1000, "teamPoints": 0}}]}
    c = make_client({"/leagues": payload})
    ligas = c.get_leagues()
    assert ligas[0].id == "L2" and ligas[0].team_id == 9


def test_get_team_extrae_ids_de_plantilla():
    payload = {
        "teamMoney": 2_000_000, "teamValue": 88_000_000,
        "players": [
            {"playerMaster": {"id": "68", "nickname": "Unai"}},
            {"playerMaster": {"id": "270", "nickname": "Guevara"}},
            {"playerMaster": {}},  # sin id -> se ignora
        ],
    }
    c = make_client({"/teams/555": payload})
    team = c.get_team("L1", 555)
    assert team.player_ids == [68, 270]
    assert team.money == 2_000_000


def test_get_money():
    c = make_client({"/money": {"teamMoney": 4_250_000, "teamInvestment": 10}})
    assert c.get_money(555) == 4_250_000


def test_get_market_parsea_entradas():
    payload = [
        {"id": "m1", "salePrice": 5_000_000, "expirationDate": "2026-09-05",
         "numberOfBids": 3, "sellerTeam": {"id": "1"},
         "playerMaster": {"id": "100", "nickname": "Fulano", "positionId": 4,
                          "marketValue": 4_800_000}},
        {"id": "m2", "salePrice": 1_000_000, "expirationDate": "2026-09-05",
         "playerMaster": {"id": "200", "nickname": "Mengano", "positionId": 2,
                          "marketValue": 900_000}},
    ]
    c = make_client({"/market": payload})
    market = c.get_market("L1")
    assert [m.player_id for m in market] == [100, 200]
    assert market[0].num_bids == 3
    assert market[0].is_direct_sale is True     # lo vende un mánager
    assert market[1].is_direct_sale is False    # lo vende la máquina


def test_error_401_pide_reloguear():
    class Sess401(FakeSession):
        def get(self, url, params=None, headers=None, timeout=None):
            return FakeResp(401, {})
    c = account.AccountClient(token="x")
    c._session = Sess401({})
    with pytest.raises(account.AccountError):
        c.get_leagues()


def test_requiere_token_o_provider():
    with pytest.raises(account.AccountError):
        account.AccountClient()


# ---- Test real end-to-end: SOLO con tus credenciales por entorno -------------
@pytest.mark.live
def test_cuenta_real_si_hay_credenciales():
    email = os.environ.get("LFP_EMAIL")
    password = os.environ.get("LFP_PASSWORD")
    if not email or not password:
        pytest.skip("Define LFP_EMAIL y LFP_PASSWORD para probar la cuenta real.")
    tb = auth.login(email, password)
    c = account.AccountClient(token=tb.access_token)
    ligas = c.get_leagues()
    assert len(ligas) >= 1
    lg = ligas[0]
    team = c.get_team(lg.id, lg.team_id)
    assert team.player_ids  # tienes jugadores
    market = c.get_market(lg.id)
    assert isinstance(market, list)
    print(f"\nLiga '{lg.name}': {lg.money:,}€, {len(team.player_ids)} jugadores, "
          f"{len(market)} en mercado")
