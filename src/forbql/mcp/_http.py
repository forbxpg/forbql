"""Where the HTTP server listens, and what it refuses before MCP sees a request.

Plain HTTP stays on the loopback: elsewhere the server needs its own certificate, or
a proxy in front that terminates TLS at an `https` public URL.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from urllib.parse import parse_qs, urlsplit

from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import FastMCP
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

PORT = 8765
"""The port `forbql mcp --http` listens on unless told otherwise."""

BODY = 1_000_000
"""Bytes a request body may hold."""

_TOKEN_PARAMETERS = frozenset({"token", "access_token", "auth", "authorization"})


class ListeningError(ValueError):
    """The server would listen somewhere plain HTTP could be read by others."""


@dataclass(frozen=True, slots=True)
class Listening:
    """Where the server listens, and how clients reach it.

    Attributes:
        host: str - Address to bind.
        port: int - Port to bind.
        tls_cert: Path | None - Certificate, when the server terminates TLS.
        tls_key: Path | None - Its private key.
        public_url: str | None - `https://…` of a proxy in front, if any.

    """

    host: str
    port: int
    tls_cert: Path | None = None
    tls_key: Path | None = None
    public_url: str | None = None

    def allowed_hosts(self) -> list[str]:
        """Name the `Host` headers a request may carry: the bind, or the public URL.

        Returns:
            list[str] - Host names; FastMCP adds the loopback names itself.

        """
        hosts = [self.host]
        if self.public_url is not None:
            hosts.append(urlsplit(self.public_url).hostname or "")
        return hosts


def listening(
    host: str,
    port: int = PORT,
    *,
    tls_cert: Path | None = None,
    tls_key: Path | None = None,
    public_url: str | None = None,
) -> Listening:
    """Check where the server is asked to listen.

    Args:
        host: str - Address to bind.
        port: int - Port to bind.
        tls_cert: Path | None - Certificate for TLS.
        tls_key: Path | None - Its private key.
        public_url: str | None - `https://…` of a proxy that terminates TLS.

    Returns:
        Listening - The checked place.

    Raises:
        ListeningError: If plain HTTP would be reachable beyond the loopback, the
            public URL is not `https`, or only half of the TLS pair is given.

    """
    if (tls_cert is None) != (tls_key is None):
        msg = "--tls-cert and --tls-key go together"
        raise ListeningError(msg)
    if public_url is not None and urlsplit(public_url).scheme != "https":
        msg = f"the public URL must be https, not {public_url}"
        raise ListeningError(msg)
    if tls_cert is None and public_url is None and not _loopback(host):
        msg = (
            f"refusing plain HTTP on {host}: give --tls-cert and --tls-key, or put "
            "a proxy that terminates TLS in front and give its --public-url https://…; "
            "in docker, publish the port on the loopback: -p 127.0.0.1:8765:8765"
        )
        raise ListeningError(msg)
    return Listening(host, port, tls_cert, tls_key, public_url)


def app_options(where: Listening) -> dict[str, object]:
    """Say how FastMCP builds the HTTP app: stateless, strict about Host and Origin.

    Args:
        where: Listening - Where the server listens.

    Returns:
        dict[str, object] - Keyword arguments for `http_app` and `run`.

    """
    return {
        "stateless_http": True,
        "host_origin_protection": True,
        "allowed_hosts": where.allowed_hosts(),
        "middleware": [Middleware(Guard)],
    }


def serve(server: FastMCP, where: Listening) -> None:
    """Run the server over HTTP until it is stopped.

    Args:
        server: FastMCP - The server.
        where: Listening - Where to listen.

    """
    uvicorn: dict[str, object] = {"access_log": False}
    if where.tls_cert is not None and where.tls_key is not None:
        uvicorn |= {
            "ssl_certfile": str(where.tls_cert),
            "ssl_keyfile": str(where.tls_key),
        }
    server.run(
        transport="http",
        host=where.host,
        port=where.port,
        show_banner=False,
        uvicorn_config=uvicorn,
        **app_options(where),
    )


class Guard:
    """Refuses a request whose query string carries a token, or whose body is too big.

    Args:
        app: ASGIApp - The app behind it.
        limit: int - Bytes a body may hold.

    """

    _app: ASGIApp
    _limit: int

    def __init__(self, app: ASGIApp, limit: int = BODY) -> None:
        self._app = app
        self._limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass a request on, or refuse it.

        Args:
            scope: Scope - The request.
            receive: Receive - Its body.
            send: Send - The response.

        """
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        raw = cast("bytes", scope.get("query_string", b""))
        query = parse_qs(raw.decode("latin-1"))
        if _TOKEN_PARAMETERS & {name.lower() for name in query}:
            refused = "send the token in the Authorization header, not the URL"
            await PlainTextResponse(refused, status_code=400)(scope, receive, send)
            return
        length = Headers(scope=scope).get("content-length")
        if length is not None and length.isdigit() and int(length) > self._limit:
            await _too_large(scope, receive, send)
            return
        seen = 0

        async def bounded() -> Message:
            nonlocal seen
            message = await receive()
            seen += len(cast("bytes", message.get("body", b"")))
            if seen > self._limit:
                raise _TooLargeError
            return message

        try:
            await self._app(scope, bounded, send)
        except _TooLargeError:
            await _too_large(scope, receive, send)


class _TooLargeError(Exception):
    """A streamed body passed the limit."""


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    """Answer 413.

    Args:
        scope: Scope - The request.
        receive: Receive - Its body.
        send: Send - The response.

    """
    response = PlainTextResponse("the request is too large", status_code=413)
    await response(scope, receive, send)


def _loopback(host: str) -> bool:
    """Tell whether an address is the machine's own.

    Args:
        host: str - An address or `localhost`.

    Returns:
        bool - True for loopback addresses and `localhost`.

    """
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
