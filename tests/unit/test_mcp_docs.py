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


def test_every_documented_forbql_mcp_line_names_options_it_has():
    guide = GUIDE.read_text(encoding="utf-8")
    commands = re.findall(r"forbql mcp (.+?)(?:\n(?!\s)|$)", guide.replace("\\\n", " "))
    command = typer.main.get_command(app)
    assert isinstance(command, TyperGroup)
    options = {name for param in command.commands["mcp"].params for name in param.opts}

    assert len(commands) >= 2
    for line in commands:
        assert set(re.findall(r"--[a-z-]+", line)) <= options, line
