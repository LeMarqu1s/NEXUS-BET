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


async def main() -> None:
    """Boucle principale NEXUS BET."""
    def shutdown_handler(*args):
        log.info("Shutdown signal received, stopping...")
        raise asyncio.CancelledError()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, shutdown_handler)
        except (ValueError, OSError):
            pass

    log.info("NEXUS BET starting...")
    ok = await alert_startup()
    if ok:
        log.info("Telegram startup message sent")
    else:
        log.warning("Telegram startup message failed (check TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)")

    try:
        await asyncio.gather(
            run_scanner(),
            run_telegram_poller(),
        )
    except asyncio.CancelledError:
        log.info("NEXUS BET stopped.")
    except Exception as e:
        log.exception("NEXUS BET fatal error: %s", e)
        try:
            await alert_error(str(e), "main loop")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    asyncio.run(main())
