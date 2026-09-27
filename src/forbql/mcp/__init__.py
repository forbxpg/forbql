"""The MCP server: tools and resources over one session, for one profile."""

from __future__ import annotations

from ._auth import NEEDS, Capabilities, TokenGate
from ._confirm import ASK, confirm
from ._instructions import instructions
from ._output import BYTES, CELL, ROWS, Fitted, clean, fit, reply, untrusted
from ._server import Opener, build_server

__all__ = (
    "ASK",
    "BYTES",
    "CELL",
    "NEEDS",
    "ROWS",
    "Capabilities",
    "Fitted",
    "Opener",
    "TokenGate",
    "build_server",
    "clean",
    "confirm",
    "fit",
    "instructions",
    "reply",
    "untrusted",
)
