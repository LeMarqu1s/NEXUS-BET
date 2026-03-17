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
    try:
        await alert_startup()
    except Exception as e:
        log.warning("Telegram startup alert failed: %s", e)

    try:
        await run_scanner()
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
