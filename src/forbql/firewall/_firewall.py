"""The firewall: runs the steps in order and turns their findings into a verdict."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forbql.policy import UnknownProfileError, load_policy, policy_hash

from ._context import CheckContext, Visibility
from ._dialects import DIALECTS
from ._rule_id import RuleId
from ._steps import (
    check_columns,
    check_complexity,
    check_functions,
    check_objects,
    check_pii,
    check_statement,
    enforce_limit,
    parse,
)
from ._verdict import Verdict, Violation

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from forbql.policy import Engine, Policy

    from ._snapshot import SchemaSnapshot


class Firewall:
    """Checks SQL against a policy. Pure: no I/O after construction.

    Args:
        policy: Policy - The policy.
        schemas: Mapping[str, SchemaSnapshot] | None - Snapshot per connection; a
            connection without one gets structural checks only.

    Raises:
        UnknownProfileError: If a snapshot is given for a connection not in the policy.

    """

    _policy: Policy
    _schemas: dict[str, SchemaSnapshot]
    _policy_hash: str
    _contexts: dict[tuple[str, str], CheckContext]

    def __init__(
        self,
        policy: Policy,
        schemas: Mapping[str, SchemaSnapshot] | None = None,
    ) -> None:
        self._policy = policy
        self._schemas = dict(schemas or {})
        self._policy_hash = policy_hash(policy)
        self._contexts = {}
        unknown = sorted(set(self._schemas) - set(policy.connections))
        if unknown:
            names = ", ".join(unknown)
            msg = f"snapshots given for connections not in the policy: {names}"
            raise UnknownProfileError(msg)

    @classmethod
    def from_policy(
        cls,
        path: str | Path,
        schemas: Mapping[str, SchemaSnapshot] | None = None,
    ) -> Firewall:
        """Build a firewall from a policy file.

        Args:
            path: str | Path - Path to the policy YAML.
            schemas: Mapping[str, SchemaSnapshot] | None - Snapshot per connection.

        Returns:
            Firewall - The firewall.

        """
        return cls(load_policy(path), schemas)

    @property
    def policy_hash(self) -> str:
        """Hash of the policy, recorded with every verdict.

        Returns:
            str - The hash.

        """
        return self._policy_hash

    def check(self, sql: str, *, connection: str, profile: str) -> Verdict:
        """Check a query for a profile of a connection.

        Args:
            sql: str - The query.
            connection: str - Connection name.
            profile: str - Profile name.

        Returns:
            Verdict - The verdict.

        """
        return run_checks(sql, self._context(connection, profile), self._policy_hash)

    def visible(self, connection: str, profile: str) -> dict[str, tuple[str, ...]]:
        """Return the columns a profile can see, per `schema.table`.

        Engines without roles enforce this themselves; SQLite's authorizer does.

        Args:
            connection: str - Connection name.
            profile: str - Profile name.

        Returns:
            dict[str, tuple[str, ...]] - Visible columns; empty if no snapshot.

        """
        visibility = self._context(connection, profile).visibility
        return {} if visibility is None else dict(visibility.columns)

    def _context(self, connection: str, profile: str) -> CheckContext:
        """Build, once, what checks for this profile need.

        Args:
            connection: str - Connection name.
            profile: str - Profile name.

        Returns:
            CheckContext - The context.

        """
        key = (connection, profile)
        if key not in self._contexts:
            found = self._policy.profile(connection, profile)
            dialect = DIALECTS[self._policy.connection(connection).engine]
            snapshot = self._schemas.get(connection)
            self._contexts[key] = CheckContext(
                dialect=dialect,
                limits=found.limits,
                allow_recursive_cte=found.allow_recursive_cte,
                functions=dialect.functions
                | {name.upper() for name in found.functions.allow},
                visibility=None
                if snapshot is None
                else Visibility.build(found, snapshot),
            )
        return self._contexts[key]


def check_structure(sql: str, engine: Engine) -> Verdict:
    """Check a query without a policy: structural and dialect rules, default limits.

    Args:
        sql: str - The query.
        engine: Engine - Engine whose dialect and rules apply.

    Returns:
        Verdict - The verdict, marked structural only.

    """
    dialect = DIALECTS[engine]
    return run_checks(
        sql,
        CheckContext(dialect=dialect, functions=dialect.functions),
        None,
    )


def run_checks(sql: str, ctx: CheckContext, policy_hash: str | None) -> Verdict:
    """Run every step; any failure of the analysis itself is a rejection.

    Args:
        sql: str - The query.
        ctx: CheckContext - Inputs of the check.
        policy_hash: str | None - Hash of the policy used.

    Returns:
        Verdict - The verdict.

    """
    try:
        return _run(sql, ctx, policy_hash)
    except RecursionError:
        violation = Violation(
            rule=RuleId.PARSE_ERROR,
            message="the query is nested too deeply",
        )
    except Exception as error:  # ruff: ignore[blind-except] - an analysis that failed must refuse, never pass
        reason = type(error).__name__
        violation = Violation(
            rule=RuleId.INTERNAL_ERROR,
            message=f"the firewall could not analyse the query ({reason})",
        )
    return _reject([violation], ctx, policy_hash)


def _run(sql: str, ctx: CheckContext, policy_hash: str | None) -> Verdict:  # ruff: ignore[too-many-return-statements] - one exit per step keeps the order visible
    """Run the steps in order, stopping at the first one that finds problems.

    Args:
        sql: str - The query.
        ctx: CheckContext - Inputs of the check.
        policy_hash: str | None - Hash of the policy used.

    Returns:
        Verdict - The verdict.

    """
    parsed = parse(sql, ctx)
    if isinstance(parsed, list):
        return _reject(parsed, ctx, policy_hash)
    query = check_statement(parsed)
    if isinstance(query, list):
        return _reject(query, ctx, policy_hash)
    # Tables before columns, so that an unknown table is reported as a table.
    if violations := check_objects(query, ctx):
        return _reject(violations, ctx, policy_hash)
    query, violations = check_columns(query, ctx)
    if violations or (violations := check_functions(query, ctx)):
        return _reject(violations, ctx, policy_hash)
    masks, violations = check_pii(query, ctx)
    if violations or (violations := check_complexity(query, ctx)):
        return _reject(violations, ctx, policy_hash)
    query, rewrites, violations = enforce_limit(query, ctx)
    if violations:
        return _reject(violations, ctx, policy_hash)
    return Verdict(
        allowed=True,
        sql=query.sql(dialect=ctx.sqlglot_dialect, comments=False),
        rewrites=tuple(rewrites),
        masks=tuple(masks),
        structural_only=ctx.visibility is None,
        policy_hash=policy_hash,
    )


def _reject(
    violations: list[Violation],
    ctx: CheckContext,
    policy_hash: str | None,
) -> Verdict:
    """Build a rejection.

    Args:
        violations: list[Violation] - Why.
        ctx: CheckContext - Inputs of the check.
        policy_hash: str | None - Hash of the policy used.

    Returns:
        Verdict - The rejection.

    """
    return Verdict(
        allowed=False,
        sql=None,
        violations=tuple(violations),
        structural_only=ctx.visibility is None,
        policy_hash=policy_hash,
    )
