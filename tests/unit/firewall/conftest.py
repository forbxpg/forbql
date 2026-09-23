from __future__ import annotations

import pytest

from forbql import Engine, Firewall
from support.firewall import make_firewall


@pytest.fixture(params=list(Engine), ids=[engine.value for engine in Engine])
def engine(request: pytest.FixtureRequest) -> Engine:
    return request.param


@pytest.fixture
def firewall(engine: Engine) -> Firewall:
    return make_firewall(engine)
