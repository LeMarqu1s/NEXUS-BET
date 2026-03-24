import os
import sys
import signal
import asyncio
import logging
import time
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s - %(message)s")
# Silence httpx to prevent ODDS_API_KEY leaking in request URLs at DEBUG level
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("NEXUS")

if os.environ.get("PAUSE_BOT", "").strip().lower() == "true":
    log.info("Bot is paused (PAUSE_BOT=true), exiting gracefully")
    sys.exit(0)


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


async def run_daily_report():
    """Sends daily P&L report to all active subscribers at 21:00 UTC."""
    from datetime import datetime, timezone
    import telegram
    token = __import__("os").getenv("TELEGRAM_BOT_TOKEN") or __import__("os").getenv("TELEGRAM_TOKEN")
    if not token:
        return
    while True:
        now = datetime.now(timezone.utc)
        # Compute seconds until next 21:00 UTC
        target = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if now >= target:
            import datetime as _dt
            target = target + _dt.timedelta(days=1)
        wait_sec = (target - now).total_seconds()
        await asyncio.sleep(wait_sec)
        try:
            bot = telegram.Bot(token=token)
            from monitoring.telegram_bot import send_daily_report
            await send_daily_report(bot)
            log.info("Daily report sent")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Daily report error: %s", e)


async def run_position_monitor():
    """Background task: TP/SL monitor + paper portfolio sync every 60s."""
    from execution.order_manager import OrderManager
    om = OrderManager()
    while True:
        try:
            # Sync paper portfolio from signals
            try:
                from monitoring.paper_portfolio import sync_from_signals
                added = sync_from_signals()
                if added:
                    log.info("Paper portfolio: +%d new trades synced", added)
            except Exception as e:
                log.debug("Paper portfolio sync: %s", e)
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
            om = OrderManager()


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
    report_task  = asyncio.create_task(run_daily_report(), name="daily_report")
    stop_task    = asyncio.create_task(stop_event.wait(), name="stop")

    done, pending = await asyncio.wait(
        [scanner_task, telegram_task, monitor_task, report_task, stop_task],
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

