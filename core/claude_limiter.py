"""
Global rate limiter for Anthropic Claude API calls.
Uses threading.Lock so it works across asyncio event loops (scoring_engine
runs Claude in ThreadPoolExecutor + asyncio.run() — a new loop per call).
All callers share one 15-second token bucket.
"""
import asyncio
import time
import threading

_tlock = threading.Lock()
_last_call: float = 0.0
_MIN_INTERVAL = 15.0  # seconds between Claude API calls


def _throttle_blocking() -> None:
    """Thread-safe blocking throttle — safe from any thread or event loop."""
    global _last_call
    with _tlock:
        wait = _MIN_INTERVAL - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()


async def claude_call_with_limit(func):
    """Rate-limited Claude call. Wraps any async callable.

    Works in:
    - Normal async code (agents.py, swarm_orchestrator.py)
    - Thread-spawned event loops (scoring_engine.py via ThreadPoolExecutor)

    On 429 → sleep 60s → return "Agent indisponible". Never retries.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _throttle_blocking)
    try:
        return await func()
    except Exception as e:
        if "429" in str(e):
            import logging
            logging.getLogger("nexus.claude_limiter").warning(
                "Anthropic 429 rate limit — sleeping 60s"
            )
            await asyncio.sleep(60)
            return "Agent indisponible"
        raise
