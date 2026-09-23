"""The attack corpus and the legitimate corpus, and the demo bank they run against."""

from __future__ import annotations

import runpy
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, ClassVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from forbql import Engine, Firewall, RuleId, SchemaSnapshot
from forbql.policy import load_policy

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).parents[2]
ATTACKS = ROOT / "attacks"
DEMO = ROOT / "deploy" / "demo"
SCHEMA = {Engine.POSTGRES: "public", Engine.MYSQL: "bank", Engine.SQLITE: "main"}
PROFILE = "analyst"

type CaseId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]


class Effect(StrEnum):
    """What must hold on a live database when the attack runs with the firewall off."""

    DENIED = "denied"
    CANARY_UNCHANGED = "canary_unchanged"
    NO_SECRETS = "no_secrets"
    BOUNDED = "bounded"


class _Strict(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class AttackCase(_Strict):
    id: CaseId
    why: str
    sql: str
    rule: RuleId
    dialects: tuple[Engine, ...] = tuple(Engine)
    effects: tuple[Effect, ...] = ()
    pending: dict[Engine, str] = Field(default_factory=dict)


class AttackFile(_Strict):
    attack_class: str = Field(alias="class")
    description: str
    cases: tuple[AttackCase, ...]


class LegitimateCase(_Strict):
    id: CaseId
    sql: str
    dialects: tuple[Engine, ...] = tuple(Engine)
    known_block: dict[Engine, str] = Field(default_factory=dict)


class LegitimateFile(_Strict):
    category: str
    cases: tuple[LegitimateCase, ...]


@cache
def attack_files() -> tuple[AttackFile, ...]:
    return tuple(
        AttackFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(ATTACKS.glob("*.yaml"))
    )


@cache
def legitimate_files() -> tuple[LegitimateFile, ...]:
    return tuple(
        LegitimateFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted((ATTACKS / "legitimate").glob("*.yaml"))
    )


def attack_runs() -> list[tuple[AttackCase, Engine]]:
    return [
        (case, engine)
        for file in attack_files()
        for case in file.cases
        for engine in case.dialects
    ]


def legitimate_runs() -> list[tuple[LegitimateCase, Engine]]:
    return [
        (case, engine)
        for file in legitimate_files()
        for case in file.cases
        for engine in case.dialects
    ]


def run_id(run: tuple[AttackCase | LegitimateCase, Engine]) -> str:
    case, engine = run
    return f"{case.id}[{engine}]"


@cache
def demo_snapshot(engine: Engine) -> SchemaSnapshot:
    """Snapshot of the demo bank, taken from the generator that writes its seeds.

    Returns:
        SchemaSnapshot - Tables and columns of the demo bank on the engine.

    """
    tables: Callable[[], list[object]] = runpy.run_path(str(DEMO / "generate.py"))[
        "build"
    ]
    schema = SCHEMA[engine]
    return SchemaSnapshot(
        default_schema=schema,
        tables={f"{schema}.{table.name}": tuple(table.columns) for table in tables()},  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType]
    )


def connection_name(engine: Engine) -> str:
    return f"bank-{engine}"


@cache
def demo_firewall() -> Firewall:
    policy = load_policy(DEMO / "forbql.yaml")
    return Firewall(
        policy,
        {connection_name(engine): demo_snapshot(engine) for engine in Engine},
    )


def rules_of(sql: str, engine: Engine, firewall: Firewall | None = None) -> set[RuleId]:
    verdict = (firewall or demo_firewall()).check(
        sql,
        connection=connection_name(engine),
        profile=PROFILE,
    )
    return {violation.rule for violation in verdict.violations}
