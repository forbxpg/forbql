"""Codes of firewall rules; part of the public API."""

from __future__ import annotations

from enum import StrEnum


class RuleId(StrEnum):
    """Rule that rejected a query. Agents and the audit log match on these codes."""

    INTERNAL_ERROR = "internal_error"
    PARSE_ERROR = "parse_error"
    MULTIPLE_STATEMENTS = "multiple_statements"
    UNSUPPORTED_SYNTAX = "unsupported_syntax"
    EXECUTABLE_COMMENT = "executable_comment"
    QUOTED_FUNCTION_NAME = "quoted_function_name"
    UNICODE_ESCAPE = "unicode_escape"
    NOT_A_QUERY = "not_a_query"
    WRITE_OPERATION = "write_operation"
    SELECT_INTO = "select_into"
    ROW_LOCK = "row_lock"
    VARIABLE = "variable"
    TABLE_NOT_ALLOWED = "table_not_allowed"
    SYSTEM_CATALOG = "system_catalog"
    TABLE_FUNCTION = "table_function"
    UNKNOWN_COLUMN = "unknown_column"
    AMBIGUOUS_COLUMN = "ambiguous_column"
    WHOLE_ROW_REFERENCE = "whole_row_reference"
    FIELD_ACCESS = "field_access"
    FUNCTION_NOT_ALLOWED = "function_not_allowed"
    QUALIFIED_FUNCTION = "qualified_function"
    CAST_NOT_ALLOWED = "cast_not_allowed"
    OPERATOR_SYNTAX = "operator_syntax"
    PII_MASKED = "pii_masked"
    PII_AGGREGATE_ONLY = "pii_aggregate_only"
    TOO_MANY_JOINS = "too_many_joins"
    SUBQUERY_TOO_DEEP = "subquery_too_deep"
    RECURSIVE_CTE = "recursive_cte"
    INVALID_LIMIT = "invalid_limit"
