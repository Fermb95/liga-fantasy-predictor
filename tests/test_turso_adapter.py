"""Tests del adaptador Turso (Bloque 13) con un cliente libsql simulado."""
import pytest

from src import db


# ---- Dobles de prueba que imitan libsql_client ----
class FakeRow:
    def __init__(self, d): self._d = d
    def asdict(self): return dict(self._d)


class FakeResultSet:
    def __init__(self, rows, last=None):
        self.rows = [FakeRow(r) for r in rows]
        self.last_insert_rowid = last


class FakeStatement:
    def __init__(self, sql, args=None): self.sql = sql; self.args = args


class FakeClient:
    def __init__(self, responder=None):
        self.executed = []       # (sql, args)
        self.batched = []        # lista de listas de Statement
        self._responder = responder or (lambda sql, args: FakeResultSet([]))

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self._responder(sql, args)

    def batch(self, stmts):
        self.batched.append(stmts)
        return [FakeResultSet([]) for _ in stmts]

    def close(self): self.closed = True


class FakeLibsql:
    Statement = FakeStatement


def make_conn(responder=None):
    client = FakeClient(responder)
    conn = db._TursoConnection("libsql://x", "tok", client=client, libsql=FakeLibsql())
    return conn, client


def test_execute_devuelve_filas_como_dict():
    conn, client = make_conn(lambda sql, args: FakeResultSet([{"id": 1, "name": "A"}]))
    row = conn.execute("SELECT * FROM t WHERE id=?", (1,)).fetchone()
    assert row == {"id": 1, "name": "A"}
    assert row["name"] == "A"                       # acceso por nombre
    # el SELECT del usuario se ejecutó con args como lista
    assert ("SELECT * FROM t WHERE id=?", [1]) in client.executed


def test_iteracion_de_cursor():
    conn, _ = make_conn(lambda sql, args: FakeResultSet([{"x": 1}, {"x": 2}]))
    assert [r["x"] for r in conn.execute("SELECT x FROM t")] == [1, 2]


def test_executemany_usa_batch():
    conn, client = make_conn()
    client.batched.clear()  # limpiar el batch del esquema inicial
    conn.executemany("INSERT INTO t (a,b) VALUES (?,?)", [(1, 2), (3, 4)])
    assert len(client.batched) == 1
    assert len(client.batched[0]) == 2
    assert client.batched[0][0].args == [1, 2]


def test_executescript_parte_en_sentencias():
    conn, client = make_conn()
    client.batched.clear()
    conn.executescript("CREATE TABLE a(x); CREATE TABLE b(y);")
    assert len(client.batched) == 1
    sqls = [s.sql for s in client.batched[0]]
    assert any("CREATE TABLE a" in s for s in sqls)
    assert any("CREATE TABLE b" in s for s in sqls)


def test_connect_usa_turso_si_hay_credenciales(monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "tok")
    creado = {}

    class Fake(db._TursoConnection):
        def __init__(self, url, token):   # evita red
            creado["url"] = url

    monkeypatch.setattr(db, "_TursoConnection", Fake)
    assert db.using_turso() is True
    conn = db.connect()
    assert creado["url"] == "libsql://x"


def test_connect_usa_sqlite_sin_credenciales(monkeypatch, tmp_path):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    assert db.using_turso() is False
    conn = db.connect(tmp_path / "x.db")
    conn.execute("SELECT 1")   # sqlite real funciona
    conn.close()
