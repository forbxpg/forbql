"""Errors raised while loading or reading a policy."""

from __future__ import annotations


class PolicyError(ValueError):
    """The policy file cannot be read, is not valid YAML, or breaks schema v1."""


class UnknownProfileError(LookupError):
    """The requested connection or profile is not in the policy."""
