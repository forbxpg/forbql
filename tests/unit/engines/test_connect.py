from __future__ import annotations

import asyncio
import builtins
import sys
from typing import TYPE_CHECKING

import pytest

from forbql.engines import ErrorClass, QueryError, connect
from forbql.policy import Engine

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from types import ModuleType

_real_import = builtins.__import__


@pytest.mark.parametrize(
    ("engine", "driver"),
    [(Engine.POSTGRES, "asyncpg"), (Engine.MYSQL, "pymysql")],
)
def test_missing_driver_names_the_extra(
    engine: Engine,
    driver: str,
    monkeypatch: pytest.MonkeyPatch,
):
    def without_driver(
        name: str,
        globals_: Mapping[str, object] | None = None,
        locals_: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> ModuleType:
        if name == driver:
            raise ModuleNotFoundError(name)
        return _real_import(name, globals_, locals_, fromlist, level)

    for module in [
        name for name in sys.modules if name.startswith(f"forbql.engines.{engine}")
    ]:
        monkeypatch.delitem(sys.modules, module)
    monkeypatch.setattr(builtins, "__import__", without_driver)

    with pytest.raises(ImportError, match=rf"pip install 'forbql\[{engine}\]'"):
        asyncio.run(connect(engine, "dsn"))


def test_errors_carry_a_hint_but_not_the_database_text():
    error = QueryError(
        ErrorClass.PERMISSION_DENIED,
        "permission denied for table secrets",
    )

    assert "secrets" not in error.hint
    assert error.detail == "permission denied for table secrets"
