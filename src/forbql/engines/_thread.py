"""Blocking driver calls on a worker thread, one at a time per connection."""

from __future__ import annotations

from asyncio import CancelledError, ensure_future, shield, to_thread, wait
from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asyncio import Lock
    from collections.abc import Callable


async def run_locked[**P, T](
    lock: Lock,
    function: Callable[P, T],
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Run a blocking call on a thread, holding the lock until the thread is done.

    Cancelling the caller cannot stop the thread. Releasing the lock at that moment
    would let the next call use the connection while this one still does.

    Args:
        lock: Lock - The connection's lock.
        function: Callable[P, T] - The blocking call.
        *args: P.args - Its positional arguments.
        **kwargs: P.kwargs - Its keyword arguments.

    Returns:
        T - What the call returned.

    Raises:
        CancelledError: If the caller is cancelled; raised once the thread is done.

    """
    async with lock:
        task = ensure_future(to_thread(function, *args, **kwargs))
        try:
            return await shield(task)
        except CancelledError:
            while not task.done():
                with suppress(CancelledError):
                    _ = await wait({task})
            if not task.cancelled():
                _ = task.exception()
            raise
