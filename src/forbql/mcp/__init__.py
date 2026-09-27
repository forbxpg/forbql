"""The MCP server: tools and resources over one session, for one profile."""

from __future__ import annotations

from ._auth import NEEDS, Capabilities, TokenGate
from ._confirm import ASK, confirm
from ._http import (
    BODY,
    PORT,
    Guard,
    Listening,
    ListeningError,
    app_options,
    listening,
    serve,
)
from ._instructions import instructions
from ._limits import BURST, CALLS, PER_SECOND, OneQueryEach, caller, rate_limit
from ._output import BYTES, CELL, ROWS, Fitted, clean, fit, reply, untrusted
from ._server import Opener, build_server

__all__ = (
    "ASK",
    "BODY",
    "BURST",
    "BYTES",
    "CALLS",
    "CELL",
    "NEEDS",
    "PER_SECOND",
    "PORT",
    "ROWS",
    "Capabilities",
    "Fitted",
    "Guard",
    "Listening",
    "ListeningError",
    "OneQueryEach",
    "Opener",
    "TokenGate",
    "app_options",
    "build_server",
    "caller",
    "clean",
    "confirm",
    "fit",
    "instructions",
    "listening",
    "rate_limit",
    "reply",
    "serve",
    "untrusted",
)
