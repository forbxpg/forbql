"""Principals, grants and tokens: who may do what with which profile."""

from __future__ import annotations

from ._capability import Capability
from ._grant import Grant
from ._principal import Principal
from ._token import TokenParts
from ._tokens import (
    DEFAULT_LIFETIME,
    MAX_LIFETIME,
    AccessDeniedError,
    IssuedToken,
    authenticate,
    issue_token,
)

__all__ = (
    "DEFAULT_LIFETIME",
    "MAX_LIFETIME",
    "AccessDeniedError",
    "Capability",
    "Grant",
    "IssuedToken",
    "Principal",
    "TokenParts",
    "authenticate",
    "issue_token",
)
