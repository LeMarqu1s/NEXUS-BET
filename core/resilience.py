"""
NEXUS CAPITAL - Resilience utilities
Retry, timeout, task wrapper — bot must never crash.
"""
from __future__ import annotations

import asyncio
import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

log = logging.getLogger("nexus.resilience")

API_TIMEOUT = 8.0
API_RETRIES = 3
API_RETRY_DELAY = 2.0
TASK_RESTART_DELAY = 5.0
TASK_MAX_BACKOFF = 300.0

T = TypeVar("T")


async def run_with_retry(
    fn: Callable[..., Any],
    *args: Any,
    retries: int = API_RETRIES,
    delay: float = API_RETRY_DELAY,
    timeout: float = API_TIMEOUT,
    name: str = "api_call",
    **kwargs: Any,
) -> Any:
    """
    Run async call with retries. Returns None on full failure, never raises.
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            if asyncio.iscoroutinefunction(fn):
                return await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
            loop = asyncio.get_event_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: fn(*args, **kwargs)),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            last_err = e
            log.warning("%s timeout (attempt %d/%d)", name, attempt + 1, retries)
        except Exception as e:
            last_err = e
            log.warning("%s failed (attempt %d/%d): %s", name, attempt + 1, retries, e)
        if attempt < retries - 1:
            await asyncio.sleep(delay)
    log.debug("%s all retries failed: %s", name, last_err)
    return None


def with_api_retry(
    retries: int = API_RETRIES,
    delay: float = API_RETRY_DELAY,
    timeout: float = API_TIMEOUT,
):
    """Decorator: wrap async method with retry + timeout. Returns None on failure."""

    def decorator(func: Callable[..., Any]):
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await run_with_retry(
                func, *args, retries=retries, delay=delay, timeout=timeout,
                name=func.__qualname__, **kwargs
            )
        return wrapper
    return decorator


async def run_task_with_restart(
    task_factory: Callable[..., Any],
    *args: Any,
    task_name: str = "task",
    **kwargs: Any,
) -> None:
    """
    Run task in infinite retry loop. task_factory must be a CALLABLE that returns
    a fresh coroutine when called. A coroutine can only be awaited ONCE — each
    restart must call the factory again to get a new coroutine.
    """
    delay = TASK_RESTART_DELAY
    while True:
        try:
            coro = task_factory(*args, **kwargs)
            if not asyncio.iscoroutine(coro):
                raise TypeError(f"{task_name}: factory must return a coroutine, got {type(coro)}")
            await coro
            log.info("%s completed normally, restarting in 5s", task_name)
            await asyncio.sleep(TASK_RESTART_DELAY)
            delay = TASK_RESTART_DELAY
        except asyncio.CancelledError:
            log.info("%s cancelled", task_name)
            raise
        except Exception as e:
            log.exception("%s crashed: %s — restarting in %.0fs", task_name, e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, TASK_MAX_BACKOFF)


def _start_time() -> float:
    return getattr(_start_time, "_t", time.monotonic())


def set_uptime_start() -> None:
    setattr(_start_time, "_t", time.monotonic())


def get_uptime_seconds() -> float:
    return time.monotonic() - getattr(_start_time, "_t", time.monotonic())
