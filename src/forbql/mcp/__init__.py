"""The MCP server: tools and resources over one session, for one profile."""

from __future__ import annotations

from ._auth import NEEDS, Capabilities, TokenGate
from ._confirm import ASK, confirm
from ._instructions import instructions
from ._limits import BURST, CALLS, PER_SECOND, OneQueryEach, caller, rate_limit
from ._output import BYTES, CELL, ROWS, Fitted, clean, fit, reply, untrusted
from ._server import Opener, build_server

__all__ = (
    "ASK",
    "BURST",
    "BYTES",
    "CALLS",
    "CELL",
    "NEEDS",
    "PER_SECOND",
    "ROWS",
    "Capabilities",
    "Fitted",
    "OneQueryEach",
    "Opener",
    "TokenGate",
    "build_server",
    "caller",
    "clean",
    "confirm",
    "fit",
    "instructions",
    "rate_limit",
    "reply",
    "untrusted",
)
