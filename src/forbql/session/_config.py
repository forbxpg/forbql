"""Settings from `FORBQL_*` environment variables."""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from forbql.policy import MaskStrategy, Profile
from forbql.store import SecretKey

DEFAULT_AUDIT_LOG = Path("forbql-audit.jsonl")
MASK_KEY_VARIABLE = "FORBQL_MASK_KEY"
_MIN_KEY_BYTES = 32


class SessionError(Exception):
    """A session cannot open: a missing DSN or key, or an unreachable database."""


class ForbqlSettings(BaseSettings):
    """Everything a session reads from the environment.

    Secrets are `SecretStr`: a DSN's password never shows in a repr, log or traceback.

    Attributes:
        dsn: dict[str, SecretStr] - DSN per connection key, from
            `FORBQL_DSN_<CONNECTION>`.
        mask_key: SecretStr | None - HMAC key for the `hash` strategy, from
            `FORBQL_MASK_KEY`.
        audit_log: Path - Audit log file, from `FORBQL_AUDIT_LOG`.
        store_dsn: SecretStr | None - The service store as the runtime role, from
            `FORBQL_STORE_DSN`; without it DSNs and the audit log stay local.
        store_owner_dsn: SecretStr | None - The store as the role that runs
            migrations, from `FORBQL_STORE_OWNER_DSN`.
        secret_key: SecretStr | None - Key that seals DSNs in the store, from
            `FORBQL_SECRET_KEY`.
        secret_key_file: Path | None - File holding that key, from
            `FORBQL_SECRET_KEY_FILE`.

    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="FORBQL_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
    )

    dsn: dict[str, SecretStr] = Field(default_factory=dict)
    mask_key: SecretStr | None = None
    audit_log: Path = DEFAULT_AUDIT_LOG
    store_dsn: SecretStr | None = None
    store_owner_dsn: SecretStr | None = None
    secret_key: SecretStr | None = None
    secret_key_file: Path | None = None


def connection_key(connection: str) -> str:
    """Turn a connection name into its key in `ForbqlSettings.dsn`.

    Args:
        connection: str - Connection name, such as `bank-postgres`.

    Returns:
        str - Such as `bank_postgres`.

    """
    return re.sub(r"[^a-z0-9]", "_", connection.lower())


def dsn_variable(connection: str) -> str:
    """Name the environment variable that holds a connection's DSN.

    Args:
        connection: str - Connection name, such as `bank-postgres`.

    Returns:
        str - Such as `FORBQL_DSN_BANK_POSTGRES`.

    """
    return "FORBQL_DSN_" + connection_key(connection).upper()


def resolve_dsn(connection: str, dsn: str | None, settings: ForbqlSettings) -> str:
    """Take the DSN given, else the connection's environment variable.

    Args:
        connection: str - Connection name.
        dsn: str | None - DSN passed by the caller.
        settings: ForbqlSettings - Settings from the environment.

    Returns:
        str - The DSN.

    Raises:
        SessionError: If neither is set.

    """
    if dsn:
        return dsn
    found = settings.dsn.get(connection_key(connection))
    if found is None:
        variable = dsn_variable(connection)
        msg = f"no DSN for connection '{connection}': pass dsn= or set {variable}"
        raise SessionError(msg)
    return found.get_secret_value()


def mask_key(profile: Profile, settings: ForbqlSettings) -> bytes | None:
    """Return the HMAC key when the profile masks anything with `hash`.

    Refusing to start beats hashing with a guessable default key.

    Args:
        profile: Profile - The profile.
        settings: ForbqlSettings - Settings from the environment.

    Returns:
        bytes | None - The key, or None when no column uses `hash`.

    Raises:
        SessionError: If a column uses `hash` and the key is missing or short.

    """
    needed = any(
        rule.strategy is MaskStrategy.HASH
        for access in profile.tables.values()
        for rule in access.pii.values()
    )
    if not needed:
        return None
    key = settings.mask_key.get_secret_value().encode() if settings.mask_key else b""
    if len(key) < _MIN_KEY_BYTES:
        need = f"{_MIN_KEY_BYTES}+ bytes"
        msg = f"the profile masks with hash: set {MASK_KEY_VARIABLE} to {need}"
        raise SessionError(msg)
    return key


def secret_key(settings: ForbqlSettings) -> SecretKey | None:
    """Load the key that seals DSNs in the store, when one is configured.

    Args:
        settings: ForbqlSettings - Settings from the environment.

    Returns:
        SecretKey | None - The key; None when neither variable is set.

    """
    if settings.secret_key is None and settings.secret_key_file is None:
        return None
    value = settings.secret_key.get_secret_value() if settings.secret_key else None
    return SecretKey.load(value, settings.secret_key_file)
