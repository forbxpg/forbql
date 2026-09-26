"""A DSN as SQLAlchemy's asyncpg dialect takes it."""

from __future__ import annotations

from sqlalchemy.engine import make_url


def sqlalchemy_url(dsn: str) -> str:
    """Point a `postgresql://` DSN at the asyncpg driver.

    Args:
        dsn: str - `postgresql://` or `postgres://`.

    Returns:
        str - `postgresql+asyncpg://`, password included.

    """
    url = make_url(dsn.replace("postgres://", "postgresql://", 1))
    return url.set(drivername="postgresql+asyncpg").render_as_string(
        hide_password=False,
    )
