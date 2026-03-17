"""
NEXUS BET - Point d'entrée principal
Connecte tous les modules: scan → edge → agents → execution → monitoring.
"""
import asyncio
import logging
import signal
import sys
from pathlib import Path

# Ajouter le projet au path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.scanner import run_scanner
from monitoring.telegram_alerts import alert_startup, alert_error
from monitoring.telegram_bot import run_telegram_poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("nexus")

_main_task: asyncio.Task | None = None
_loop: asyncio.AbstractEventLoop | None = None


def _signal_handler(sig: int, frame: object) -> None:
    """Handle SIGINT/SIGTERM - cancel main task for graceful shutdown."""
    log.info("Shutdown signal received, stopping gracefully...")
    if _main_task and _loop and not _main_task.done():
        _loop.call_soon_threadsafe(_main_task.cancel)


async def main() -> None:
    """Boucle principale NEXUS BET."""
    global _main_task, _loop

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except (ValueError, OSError):
            pass

    log.info("NEXUS BET starting...")
    try:
        ok = await alert_startup()
        if ok:
            log.info("Telegram startup message sent")
        else:
            log.warning("Telegram startup message failed (check TELEGRAM_TOKEN, TELEGRAM_CHAT_ID in env)")
    except Exception as e:
        log.warning("Telegram startup error: %s", e)

    _loop = asyncio.get_running_loop()
    _main_task = asyncio.current_task()
    assert _main_task is not None

    scanner_task = asyncio.create_task(run_scanner())
    poller_task = asyncio.create_task(run_telegram_poller())
    try:
        await asyncio.gather(scanner_task, poller_task)
    except asyncio.CancelledError:
        log.info("Shutdown, cancelling tasks...")
        scanner_task.cancel()
        poller_task.cancel()
        try:
            await asyncio.gather(scanner_task, poller_task, return_exceptions=True)
        except asyncio.CancelledError:
            pass
        log.info("NEXUS BET stopped gracefully.")
    except Exception as e:
        log.exception("NEXUS BET fatal error: %s", e)
        scanner_task.cancel()
        poller_task.cancel()
        try:
            await asyncio.gather(scanner_task, poller_task, return_exceptions=True)
        except Exception:
            pass
        try:
            await alert_error(str(e), "main loop")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted.")
    except asyncio.CancelledError:
        log.info("Stopped.")
