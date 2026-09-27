"""Asking the person at the client whether an expensive query may run.

The agent cannot answer for them: the question goes to the client as elicitation.
Before MCP 2026-07-28 the server asks and waits; from that version the tool answers
with the question, the client asks the person and calls again with the answer, and
the sealed request state ties that answer to this exact query.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from fastmcp.exceptions import FastMCPError
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
)
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

if TYPE_CHECKING:
    from fastmcp import Context

ASK = "confirm"
"""The key of the one question this server asks."""

_ANSWER = {
    "type": "object",
    "properties": {"run": {"type": "boolean", "title": "Run the query"}},
    "required": ["run"],
}


async def confirm(
    ctx: Context,
    *,
    message: str,
    query: str,
) -> bool | InputRequiredResult:
    """Ask the person whether a query may run.

    Args:
        ctx: Context - The call.
        message: str - What the person reads.
        query: str - The query the answer is for.

    Returns:
        bool | InputRequiredResult - The answer; or, on a 2026-07-28 connection
            before the person has answered, the question to return to the client.
            A client that cannot ask means no.

    """
    digest = hashlib.sha256(query.encode()).hexdigest()
    answers = ctx.input_responses
    if answers is not None:
        answer = answers.get(ASK)
        return (
            ctx.request_state == digest
            and isinstance(answer, ElicitResult)
            and answer.action == "accept"
            and (answer.content or {}).get("run") is True
        )
    context = ctx.request_context
    if context is not None and context.protocol_version in MODERN_PROTOCOL_VERSIONS:
        return InputRequiredResult(
            input_requests={
                ASK: ElicitRequest(
                    params=ElicitRequestFormParams(
                        message=message,
                        requested_schema=_ANSWER,
                    ),
                ),
            },
            request_state=digest,
        )
    try:
        answer = await ctx.elicit(message, response_type=bool)
    except FastMCPError:
        return False
    return isinstance(answer, AcceptedElicitation) and answer.data is True
