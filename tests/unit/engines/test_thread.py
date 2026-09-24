from __future__ import annotations

import asyncio
import threading

import pytest

from forbql.engines._thread import run_locked


def test_the_call_runs_on_a_thread_under_the_lock():
    async def go() -> tuple[bool, str]:
        lock = asyncio.Lock()
        seen = await run_locked(
            lock,
            lambda: (lock.locked(), threading.current_thread().name),
        )
        return seen[0], seen[1]

    locked, name = asyncio.run(go())

    assert locked
    assert name != threading.main_thread().name


def test_cancelling_the_caller_keeps_the_lock_until_the_thread_ends():
    started, release = threading.Event(), threading.Event()

    def slow() -> str:
        started.set()
        release.wait(5)
        return "done"

    async def go() -> list[bool]:
        lock = asyncio.Lock()
        task = asyncio.create_task(run_locked(lock, slow))
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0.05)
        held_while_running = lock.locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        return [held_while_running, lock.locked()]

    assert asyncio.run(go()) == [True, False]


def test_errors_of_the_call_reach_the_caller():
    def fail() -> None:
        msg = "boom"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(run_locked(asyncio.Lock(), fail))
