from __future__ import annotations

import asyncio

import psycopg
import pytest

from forbql import Engine
from forbql.engines import QueryError
from forbql.engines.postgres import PostgresEngine
from forbql.store._url import sqlalchemy_url
from support.stand import ADMIN, PROBE, READER, as_owner
from support.store import STORE_APP, STORE_OWNER, STORE_SUPERUSER, store_sql
from support.touched import touched

_PLAIN = "postgresql://forbql_app:wrong@127.0.0.1:55432/forbql_test"


def _refuse(seen: list[str]):
    async def connect(dsn: str) -> None:  # ruff: ignore[unused-async] - stands in for asyncpg.connect
        seen.append(dsn)
        message = "do not dial"
        raise OSError(message)

    return connect


@pytest.fixture
def dialed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(
        "forbql.engines.postgres._engine.asyncpg_connect",
        _refuse(seen),
    )
    return seen


def test_missing_sslmode_names_the_parameter(dialed: list[str]):
    with pytest.raises(ValueError, match="sslmode"):
        asyncio.run(PostgresEngine.connect("postgresql://reader@127.0.0.1/bank"))

    assert dialed == []


@pytest.mark.parametrize("mode", ["prefer", "Prefer"])
def test_prefer_is_refused(dialed: list[str], mode: str):
    with pytest.raises(ValueError, match="prefer"):
        asyncio.run(
            PostgresEngine.connect(
                f"postgresql://reader@127.0.0.1/bank?sslmode={mode}",
            ),
        )

    assert dialed == []


def test_allow_is_refused(dialed: list[str]):
    with pytest.raises(ValueError, match="allow"):
        asyncio.run(
            PostgresEngine.connect("postgresql://reader@127.0.0.1/bank?sslmode=allow"),
        )

    assert dialed == []


def test_disable_without_the_opt_in_is_refused(dialed: list[str]):
    with pytest.raises(ValueError, match="forbql-insecure=1"):
        asyncio.run(
            PostgresEngine.connect(
                "postgresql://reader@127.0.0.1/bank?sslmode=disable",
            ),
        )

    assert dialed == []


def test_a_value_other_than_1_is_not_the_opt_in(dialed: list[str]):
    with pytest.raises(ValueError, match="forbql-insecure=1"):
        asyncio.run(
            PostgresEngine.connect(
                "postgresql://reader@127.0.0.1/bank?sslmode=disable&forbql-insecure=true",
            ),
        )

    assert dialed == []


def test_disable_with_the_opt_in_strips_the_flag(dialed: list[str]):
    with pytest.raises(QueryError):
        asyncio.run(
            PostgresEngine.connect(
                "postgresql://reader:p%40ss@127.0.0.1/bank?sslmode=disable&forbql-insecure=1",
            ),
        )

    assert dialed == ["postgresql://reader:p%40ss@127.0.0.1/bank?sslmode=disable"]


def test_other_parameters_survive_stripping_the_flag(dialed: list[str]):
    with pytest.raises(QueryError):
        asyncio.run(
            PostgresEngine.connect(
                "postgresql://h/db?application_name=forbql&sslmode=disable&forbql-insecure=1",
            ),
        )

    assert dialed == [
        "postgresql://h/db?application_name=forbql&sslmode=disable",
    ]


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_explicit_tls_passes_through(dialed: list[str], mode: str):
    dsn = f"postgresql://reader@127.0.0.1/bank?sslmode={mode}"

    with pytest.raises(QueryError):
        asyncio.run(PostgresEngine.connect(dsn))

    assert dialed == [dsn]


def test_require_with_the_opt_in_stays_require(dialed: list[str]):
    with pytest.raises(QueryError):
        asyncio.run(
            PostgresEngine.connect(
                "postgresql://reader@127.0.0.1/bank?forbql-insecure=1&sslmode=require",
            ),
        )

    assert dialed == ["postgresql://reader@127.0.0.1/bank?sslmode=require"]


def test_an_unknown_sslmode_is_refused(dialed: list[str]):
    with pytest.raises(ValueError, match="sslmode"):
        asyncio.run(
            PostgresEngine.connect(
                "postgresql://reader@127.0.0.1/bank?sslmode=sometimes",
            ),
        )

    assert dialed == []


def test_postgres_scheme_passes_through(dialed: list[str]):
    dsn = "postgres://reader@127.0.0.1/bank?sslmode=verify-full"

    with pytest.raises(QueryError):
        asyncio.run(PostgresEngine.connect(dsn))

    assert dialed == [dsn]


@pytest.mark.parametrize("role", [READER, ADMIN, PROBE])
def test_local_postgres_roles_opt_into_plaintext(
    dialed: list[str],
    role: dict[Engine, str],
):
    dsn = role[Engine.POSTGRES]
    base, _, _ = dsn.partition("?")

    assert "sslmode=disable" in dsn
    assert "forbql-insecure=1" in dsn
    with pytest.raises(QueryError):
        asyncio.run(PostgresEngine.connect(dsn))

    assert dialed == [f"{base}?sslmode=disable"]


@pytest.mark.parametrize("dsn", [STORE_SUPERUSER, STORE_OWNER, STORE_APP])
def test_store_dsns_opt_into_plaintext(dialed: list[str], dsn: str):
    base, _, _ = dsn.partition("?")

    assert "sslmode=disable" in dsn
    assert "forbql-insecure=1" in dsn
    with pytest.raises(QueryError):
        asyncio.run(PostgresEngine.connect(dsn))

    assert dialed == [f"{base}?sslmode=disable"]


def test_sqlalchemy_store_url_drops_the_opt_in_and_maps_sslmode():
    rendered = sqlalchemy_url(STORE_APP)

    assert "forbql-insecure" not in rendered
    assert "sslmode=" not in rendered
    assert "ssl=disable" in rendered


def test_a_store_url_without_tls_parameters_only_changes_driver():
    assert sqlalchemy_url(_PLAIN) == _PLAIN.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1,
    )


def test_stand_owner_drops_the_opt_in(monkeypatch: pytest.MonkeyPatch):
    seen: list[str] = []
    monkeypatch.setattr("support.stand.asyncpg.connect", _refuse(seen))

    with pytest.raises(OSError, match="do not dial"):
        as_owner(Engine.POSTGRES, ["SELECT 1"])

    assert seen == [
        "postgresql://postgres:demo-local-only@127.0.0.1:55433/bank?sslmode=disable",
    ]


def test_store_sql_drops_the_opt_in(monkeypatch: pytest.MonkeyPatch):
    seen: list[str] = []
    monkeypatch.setattr("support.store.asyncpg.connect", _refuse(seen))

    with pytest.raises(OSError, match="do not dial"):
        store_sql(STORE_APP, "SELECT 1")

    assert seen == [
        "postgresql://forbql_app:app-local-only@127.0.0.1:55432/forbql_test?sslmode=disable",
    ]


def test_planner_trace_drops_the_opt_in(monkeypatch: pytest.MonkeyPatch, tmp_path):
    seen: list[str] = []

    def connect(dsn: str) -> None:
        seen.append(dsn)
        message = "do not dial"
        raise psycopg.OperationalError(message)

    monkeypatch.setattr("support.touched.psycopg.connect", connect)

    assert touched(Engine.POSTGRES, "SELECT 1", tmp_path / "unused") is None
    assert seen == [
        "postgresql://postgres:demo-local-only@127.0.0.1:55433/bank?sslmode=disable",
    ]
