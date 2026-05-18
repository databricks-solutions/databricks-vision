"""Background-task helpers.

Pattern note: `asyncio.create_task(coro)` returns a Task object. The event loop
holds only a *weak* reference to it, so if no caller retains a strong reference,
the Task can be garbage-collected mid-execution and the coroutine silently
cancelled. See https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task

We use this module-level set + done-callback pattern to keep a strong reference
until the task finishes. All fire-and-forget Phase-2 (analyze + embed) work
should go through `spawn_bg`.
"""
from __future__ import annotations

import asyncio
from typing import Coroutine, Set

_BG_TASKS: Set[asyncio.Task] = set()


def spawn_bg(coro: Coroutine) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task
