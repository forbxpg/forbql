"""Database engines forbql protects."""

from __future__ import annotations

from enum import StrEnum


class Engine(StrEnum):
    """Engine of a connection; selects the SQL dialect and its security rules."""

    POSTGRES = "postgres"
    MYSQL = "mysql"
    SQLITE = "sqlite"
