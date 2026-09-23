"""Step 1: parse exactly one statement, rejecting what the parser may misread."""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.tokenizer_core import Token, TokenType

from forbql.firewall._rule_id import RuleId
from forbql.firewall._verdict import Span, Violation
from forbql.policy import Engine

if TYPE_CHECKING:
    from forbql.firewall._context import CheckContext


MAX_SQL_LENGTH = 100_000


def parse(sql: str, ctx: CheckContext) -> exp.Expr | list[Violation]:
    """Parse one statement in the connection's dialect and normalize identifiers.

    Args:
        sql: str - The SQL the caller sent.
        ctx: CheckContext - Inputs of the check.

    Returns:
        exp.Expr | list[Violation] - The tree, or why it cannot be trusted.

    """
    violations = _check_text(sql, ctx.dialect.engine)
    if violations:
        return violations

    dialect = Dialect.get_or_raise(ctx.sqlglot_dialect)
    try:
        violations = _check_tokens(dialect.tokenize(sql), ctx.dialect.engine)
        statements = [
            tree for tree in sqlglot.parse(sql, read=dialect) if tree is not None
        ]
    except SqlglotError as error:
        return [
            Violation(
                rule=RuleId.PARSE_ERROR,
                message=f"cannot parse the query: {error}",
            ),
        ]
    if violations:
        return violations

    if len(statements) != 1:
        return [
            Violation(
                rule=RuleId.MULTIPLE_STATEMENTS if statements else RuleId.PARSE_ERROR,
                message=f"expected one statement, got {len(statements)}",
                hint="send exactly one statement per request",
            ),
        ]

    if statements[0].find(exp.Command) is not None:
        return [
            Violation(
                rule=RuleId.UNSUPPORTED_SYNTAX,
                message="the query uses syntax the firewall cannot analyse",
            ),
        ]

    return normalize_identifiers(statements[0], dialect=dialect)


def _check_text(sql: str, engine: Engine) -> list[Violation]:
    """Reject what must be caught before tokenizing.

    Args:
        sql: str - The SQL the caller sent.
        engine: Engine - The engine.

    Returns:
        list[Violation] - Problems found.

    """
    if len(sql) > MAX_SQL_LENGTH:
        message = f"query is longer than {MAX_SQL_LENGTH} characters"
        return [Violation(rule=RuleId.PARSE_ERROR, message=message)]
    if engine is Engine.MYSQL and "/*!" in sql:
        # MySQL runs the body of /*! ... */ as SQL while parsers treat it as a comment.
        # Matching the raw text also catches it after `--` without a space, which MySQL
        # does not treat as a comment either.
        start = sql.index("/*!")
        return [
            Violation(
                rule=RuleId.EXECUTABLE_COMMENT,
                message="MySQL executable comments /*! ... */ are not allowed",
                hint="remove the comment",
                span=Span(start=start, end=start + 3),
            ),
        ]
    return []


def _check_tokens(tokens: list[Token], engine: Engine) -> list[Violation]:
    """Reject token patterns the AST no longer shows.

    Args:
        tokens: list[Token] - Tokens of the query.
        engine: Engine - The engine.

    Returns:
        list[Violation] - Problems found.

    """
    violations: list[Violation] = []
    for current, following in pairwise(tokens):
        if (
            current.token_type is TokenType.IDENTIFIER
            and following.token_type is TokenType.L_PAREN
        ):
            # sqlglot maps "Lower"(x) onto LOWER(x), but a quoted name is case-sensitive
            # and may resolve to a user-defined function.
            violations.append(
                Violation(
                    rule=RuleId.QUOTED_FUNCTION_NAME,
                    message=f"quoted name {current.text} before '(' is not allowed",
                    hint="write function names without quotes",
                    span=Span(start=current.start, end=current.end + 1),
                ),
            )

        if (
            engine is Engine.POSTGRES
            and current.text.upper() == "U"
            and following.token_type is TokenType.AMP
            and following.start == current.end + 1
        ):
            violations.append(
                Violation(
                    rule=RuleId.UNICODE_ESCAPE,
                    message="U& unicode escapes are not allowed",
                    hint="write the identifier or string literally",
                    span=Span(start=current.start, end=following.end + 1),
                ),
            )

    return violations
