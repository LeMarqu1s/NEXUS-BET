import asyncio
import logging
import signal
import time
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s - %(message)s")
# Silence httpx to prevent ODDS_API_KEY leaking in request URLs at DEBUG level
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("NEXUS")


async def run_scanner():
    from core.scanner_ws import run_forever
    while True:
        try:
            await run_forever()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Scanner crashed: %s, restart in 5s", e)
            await asyncio.sleep(5)


async def run_telegram():
    from monitoring.telegram_bot import run_forever
    while True:
        try:
            await run_forever()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Telegram crashed: %s, restart in 5s", e)
            await asyncio.sleep(5)


async def run_position_monitor():
    from execution.order_manager import OrderManager
    while True:
        om = OrderManager()
        try:
            await om.monitor_open_positions(interval_sec=60.0)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Position monitor crashed: %s, restart in 30s", e)
            await asyncio.sleep(30)
        finally:
            try:
                await om.client.close()
            except Exception:
                pass


async def main():
    log.info("NEXUS BET starting...")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_sigterm():
        log.info("SIGTERM reçu — shutdown gracieux")
        stop_event.set()

    try:
        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)
        loop.add_signal_handler(signal.SIGINT, _on_sigterm)
    except NotImplementedError:
        pass  # Windows fallback

    scanner_task = asyncio.create_task(run_scanner(), name="scanner")
    telegram_task = asyncio.create_task(run_telegram(), name="telegram")
    monitor_task = asyncio.create_task(run_position_monitor(), name="position_monitor")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop")

    done, pending = await asyncio.wait(
        [scanner_task, telegram_task, monitor_task, stop_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    log.info("Shutdown en cours — annulation des tâches...")
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    log.info("Shutdown terminé")


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except (KeyboardInterrupt, SystemExit):
            log.info("NEXUS BET arrêté")
            break
        except Exception as e:
            log.error("Fatal: %s, restart in 10s", e)
            time.sleep(10)

