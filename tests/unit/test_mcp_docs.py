"""The client configuration in CONTRIBUTING names options `forbql mcp` has."""

from __future__ import annotations

import json
import re
from pathlib import Path

import typer
from typer.core import TyperGroup

from forbql.cli import app

GUIDE = Path(__file__).parents[2] / "CONTRIBUTING.md"


def test_the_desktop_configuration_runs_the_command_as_documented():
    [block] = re.findall(
        r"```json\n(.*?)```",
        GUIDE.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    [server] = json.loads(block)["mcpServers"].values()
    command = typer.main.get_command(app)
    assert isinstance(command, TyperGroup)
    options = {name for param in command.commands["mcp"].params for name in param.opts}

    assert server["args"][0] == "mcp"
    assert {arg for arg in server["args"][1:] if arg.startswith("--")} <= options
