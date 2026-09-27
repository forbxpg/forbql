from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from starlette.responses import PlainTextResponse

from forbql.mcp import Guard, ListeningError, app_options, listening

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.types import Receive, Scope, Send

CERT, KEY = Path("cert.pem"), Path("key.pem")


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_plain_http_may_listen_on_the_loopback(host: str):
    assert listening(host).host == host


def test_plain_http_elsewhere_is_refused_with_the_ways_out():
    with pytest.raises(ListeningError) as refused:
        _ = listening("0.0.0.0")  # ruff: ignore[hardcoded-bind-all-interfaces] - the address under test

    assert "--tls-cert" in str(refused.value)
    assert "--public-url https://" in str(refused.value)
    assert "-p 127.0.0.1:8765:8765" in str(refused.value)


def test_elsewhere_is_fine_with_a_certificate_or_a_proxy_holding_one():
    everywhere = "0.0.0.0"  # ruff: ignore[hardcoded-bind-all-interfaces]
    served = listening(
        everywhere,
        tls_cert=CERT,
        tls_key=KEY,
        public_url="https://mcp.example.com:8765",
    )
    proxied = listening(everywhere, public_url="https://mcp.example.com")

    assert served.allowed_hosts() == [everywhere, "mcp.example.com"]
    assert proxied.allowed_hosts() == [everywhere, "mcp.example.com"]


def test_a_certificate_beyond_the_loopback_needs_the_name_clients_use():
    everywhere = "0.0.0.0"  # ruff: ignore[hardcoded-bind-all-interfaces]

    with pytest.raises(ListeningError, match="give --public-url"):
        _ = listening(everywhere, tls_cert=CERT, tls_key=KEY)


@pytest.mark.parametrize(
    ("given", "message"),
    [
        ({"public_url": "http://mcp.example.com"}, "must be https"),
        ({"tls_cert": CERT}, "go together"),
    ],
)
def test_a_half_way_setup_is_refused(given: dict[str, object], message: str):
    with pytest.raises(ListeningError, match=message):
        _ = listening("127.0.0.1", **given)  # pyright: ignore[reportArgumentType]


def test_the_app_is_stateless_and_strict_about_host_and_origin():
    options = app_options(listening("127.0.0.1"))

    assert options["stateless_http"] is True
    assert options["host_origin_protection"] is True
    assert options["allowed_hosts"] == ["127.0.0.1"]


async def echo(scope: Scope, receive: Receive, send: Send) -> None:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            break
    await PlainTextResponse(f"{len(body)} bytes")(scope, receive, send)


def send(url: str, content: bytes | AsyncIterator[bytes] = b"") -> tuple[int, str]:
    async def go() -> tuple[int, str]:
        transport = httpx.ASGITransport(app=Guard(echo, limit=10))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as http:
            answer = await http.post(url, content=content)
            return answer.status_code, answer.text

    return asyncio.run(go())


async def chunks() -> AsyncIterator[bytes]:
    for _ in range(3):
        await asyncio.sleep(0)
        yield b"0123456"


def test_a_token_in_the_url_is_refused():
    assert send("/mcp?access_token=fql_x")[0] == 400
    assert send("/mcp?Token=fql_x")[0] == 400
    assert send("/mcp?page=2") == (200, "0 bytes")


def test_a_body_past_the_limit_is_refused_whether_announced_or_streamed():
    assert send("/mcp", b"0123456789") == (200, "10 bytes")
    assert send("/mcp", b"0123456789A")[0] == 413
    assert send("/mcp", chunks())[0] == 413
