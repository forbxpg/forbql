"""A DSN as SQLAlchemy's asyncpg dialect takes it."""

from __future__ import annotations

from sqlalchemy.engine import make_url


def sqlalchemy_url(dsn: str) -> str:
    """Point a `postgresql://` DSN at the asyncpg driver.

    `forbql-insecure` is removed: asyncpg would treat it as a server setting.
    `sslmode` is renamed to `ssl`, the keyword asyncpg accepts when SQLAlchemy
    passes the query string as connect arguments.

    Args:
        dsn: str - `postgresql://` or `postgres://`.

    Returns:
        str - `postgresql+asyncpg://`, password included.

    """
    url = make_url(dsn.replace("postgres://", "postgresql://", 1))
    original = dict(url.query)
    query = dict(original)
    _ = query.pop("forbql-insecure", None)
    if "sslmode" in query:
        query["ssl"] = query.pop("sslmode")
    if query != original:
        url = url.set(query=query)
    return url.set(drivername="postgresql+asyncpg").render_as_string(
        hide_password=False,
    )
