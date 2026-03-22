"""
NEXUS CAPITAL - Master Loop (Point d'entrée principal)
Chef d'orchestre 24h/24 : Scan → Swarm → DeFi Yield → Exécution.
BULLETPROOF: chaque tâche a son propre retry loop, return_exceptions=True, jamais de crash.
"""
import asyncio
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# Ajouter le projet au path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.resilience import run_task_with_restart, set_uptime_start
from core.scanner_ws import run_scanner_ws
from monitoring.telegram_alerts import alert_startup, alert_error
from monitoring.telegram_bot import run_telegram_poller

# Phase 5 - Swarm Intelligence + DeFi Yield
_import_error = ""
try:
    from paperclip_bridge import get_pending_signals, clear_signal
    from swarm_orchestrator import should_deploy_swarm, run_swarm
    from defi_yield_manager import (
        update_yield_and_export,
        on_swarm_approved,
        execute_flash_withdraw,
    )
    _SWARM_DEFI_AVAILABLE = True
except ImportError as e:
    _SWARM_DEFI_AVAILABLE = False
    _import_error = str(e)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("nexus")

_main_task: asyncio.Task | None = None
_loop: asyncio.AbstractEventLoop | None = None
_shutdown_requested = False


def _signal_handler(sig: int, frame: object) -> None:
    """Handle SIGINT/SIGTERM - graceful shutdown."""
    global _shutdown_requested
    if _shutdown_requested:
        log.info("Second signal received, forcing exit.")
        sys.exit(1)
    _shutdown_requested = True
    log.info("Shutdown signal received (sig=%s), stopping gracefully...", sig)
    if _main_task and _loop and not _main_task.done():
        _loop.call_soon_threadsafe(_main_task.cancel)


async def _swarm_loop() -> None:
    """
    Boucle Swarm : poll les signaux critiques, déploie l'Essaim.
    Si approuvé → envoie suggestion CEO (Wealth Manager) avec [Approuver] [Attendre].
    Pas d'exécution auto : le CEO valide via Telegram.
    """
    if not _SWARM_DEFI_AVAILABLE:
        log.warning("Swarm/DeFi modules unavailable: %s", _import_error or "ImportError")
        return

    try:
        from monitoring.telegram_wealth_manager import get_kelly_fraction, get_risk_profile
        from monitoring.telegram_alerts import send_wealth_suggestion
        from defi_yield_manager import get_yield_state, on_swarm_approved
    except ImportError:
        log.warning("Wealth Manager modules unavailable for swarm flow")
        return

    processed: set[tuple[str, str]] = set()

    while True:
        try:
            await asyncio.sleep(15)

            for sig in get_pending_signals():
                key = (str(sig.get("market_id", "")), str(sig.get("side", "")))
                if key in processed:
                    continue
                if not should_deploy_swarm(sig):
                    continue

                # Inject Kelly du profil Wealth Manager
                sig["kelly_fraction"] = get_kelly_fraction()

                log.info(
                    "[SWARM] Signal critique détecté | market=%s side=%s edge=%.1f%% → déploiement Essaim",
                    sig.get("market_id"),
                    sig.get("side"),
                    sig.get("edge_pct", 0),
                )

                result = await run_swarm(sig)
                processed.add(key)
                clear_signal(str(sig.get("market_id", "")), str(sig.get("side", "")))

                if result.approved:
                    log.info(
                        "[SWARM] Essaim VALIDE | %s %s | %.0f%% YES (%d/%d) → suggestion CEO",
                        result.market_id,
                        result.side,
                        result.pct_yes,
                        result.votes_yes,
                        result.votes_yes + result.votes_no,
                    )
                    state = get_yield_state()
                    profile = get_risk_profile()
                    from monitoring.telegram_wealth_manager import compute_suggested_amount_usd

                    # LADDER_MODE_ANCHOR
                    suggested = compute_suggested_amount_usd(state.total_usdc, profile)
                    limit_price = float(sig.get("polymarket_price", 0.5))
                    if limit_price <= 0:
                        limit_price = 0.5
                    on_swarm_approved({**sig, "kelly_fraction": get_kelly_fraction(), "amount_usd": suggested})
                    sent = await send_wealth_suggestion(
                        balance_usdc=state.total_usdc,
                        market_id=result.market_id,
                        question=result.question or str(sig.get("question", ""))[:80],
                        outcome=result.side,
                        side="BUY",
                        pct_yes=result.pct_yes,
                        profile=profile,
                        suggested_amount=suggested,
                        limit_price=limit_price,
                    )
                    if sent:
                        log.info("[WEALTH] Suggestion CEO envoyée | %.2f$ | %s", suggested, result.market_id)
                else:
                    log.info(
                        "[SWARM] Essaim REJETÉ | %s %s | %.0f%% YES → pas d'exécution",
                        result.market_id,
                        result.side,
                        result.pct_yes,
                    )

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning("swarm_loop error: %s", e)


async def _auto_trade_loop() -> None:
    """
    Auto-trade: STRONG_BUY → execute immediately.
    BUY → Telegram confirmation, 30min timeout → auto-execute.
    """
    try:
        from monitoring.auto_trade import (
            is_auto_trade_enabled,
            process_signal,
            get_and_clear_expired_pending,
            execute_signal,
        )
        from monitoring.telegram_alerts import send_telegram_message
        from paperclip_bridge import get_pending_signals, clear_signal
    except ImportError as e:
        log.debug("auto_trade_loop: %s", e)
        return

    async def _send(msg: str, reply_markup=None):
        await send_telegram_message(msg, reply_markup=reply_markup)

    processed: set[tuple[str, str]] = set()

    while True:
        try:
            await asyncio.sleep(10)

            if is_auto_trade_enabled():
                for sig in get_pending_signals():
                    key = (str(sig.get("market_id", "")), str(sig.get("side", "")))
                    if key in processed:
                        continue
                    processed.add(key)
                    try:
                        await process_signal(sig, _send)
                        clear_signal(str(sig.get("market_id", "")), str(sig.get("side", "")))
                    except Exception as e:
                        log.warning("auto_trade process_signal: %s", e)

                for expired in get_and_clear_expired_pending():
                    sig = expired.get("signal")
                    if sig:
                        from monitoring.auto_trade import is_daily_drawdown_breached, get_open_positions_count, get_max_positions
                        if is_daily_drawdown_breached() or get_open_positions_count() >= get_max_positions():
                            await _send(f"⏱ BUY timeout ignoré (drawdown ou max positions)")
                        else:
                            order_id = await execute_signal(sig)
                            if order_id:
                                await _send(f"⏱ <b>BUY auto-exécuté</b> (timeout 30min)\n{sig.get('question','')[:50]}...\nOrder: {order_id}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning("auto_trade_loop error: %s", e)


# ANTI_SYBIL_ANCHOR
async def _copy_trader_loop() -> None:
    """
    Copy Wallet : surveille les whale_wallets, copie les trades récents (< 5min)
    sur marchés où on n'a pas de position.
    """
    try:
        from monitoring.telegram_wealth_manager import get_whale_wallets, get_copy_trade_enabled
        from monitoring.auto_trade import process_signal, is_auto_trade_enabled
        from monitoring.trade_logger import trade_logger
        from monitoring.telegram_alerts import send_telegram_message
        import httpx
    except ImportError as e:
        log.debug("copy_trader_loop: %s", e)
        return

    async def _send(msg: str, reply_markup=None):
        await send_telegram_message(msg, reply_markup=reply_markup)

    processed: set[tuple[str, str, int]] = set()

    while True:
        try:
            await asyncio.sleep(60)

            if not get_copy_trade_enabled():
                continue

            wallets = get_whale_wallets()
            if not wallets:
                continue

            positions = {(p.get("market_id"), p.get("outcome")) for p in trade_logger.get_positions()}
            now_ts = int(time.time())

            async with httpx.AsyncClient(timeout=15.0) as client:
                for addr in wallets:
                    try:
                        r = await client.get(
                            "https://data-api.polymarket.com/trades",
                            params={"funder": addr, "size": 5},
                        )
                        if r.status_code != 200:
                            continue
                        trades = r.json()
                        if not isinstance(trades, list):
                            continue

                        for t in trades:
                            ts = int(t.get("timestamp") or 0)
                            if now_ts - ts > 300:
                                continue
                            mid = str(t.get("conditionId") or t.get("condition_id") or "")
                            outcome = str(t.get("outcome") or "Yes")
                            side = str(t.get("side") or "BUY")
                            if side.upper() != "BUY":
                                continue
                            if (mid, outcome) in positions:
                                continue
                            key = (addr[:16], mid, ts)
                            if key in processed:
                                continue
                            processed.add(key)

                            size = float(t.get("size") or 0)
                            price = float(t.get("price") or 0.5)
                            amount = size * price
                            title = (t.get("title") or mid)[:50]

                            sig = {
                                "market_id": mid,
                                "side": outcome,
                                "outcome": outcome,
                                "polymarket_price": price,
                                "question": title,
                                "edge_pct": 0,
                                "kelly_fraction": 0.02,
                                "confidence": 0.5,
                                "source": "copy_trader",
                            }

                            log.info(
                                "COPY: wallet %s → %s %s $%.0f",
                                addr[:8],
                                mid[:16] if mid else "?",
                                outcome,
                                amount,
                            )

                            if is_auto_trade_enabled():
                                await process_signal(sig, _send)

                    except Exception as e:
                        log.debug("copy_trader wallet %s: %s", addr[:8], e)

            if len(processed) > 200:
                processed = set(list(processed)[-100:])

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning("copy_trader_loop error: %s", e)


async def _anti_sybil_loop() -> None:
    """Boucle Anti-Sybil : détecte Mirror Trading sur baleines, alerte si suspect."""
    try:
        from monitoring.anti_sybil_checker import check_mirror_trading
    except ImportError:
        return
    while True:
        try:
            await asyncio.sleep(300)  # toutes les 5 min
            await check_mirror_trading()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.debug("anti_sybil_loop: %s", e)


async def _defi_yield_loop() -> None:
    """
    Boucle DeFi Yield : met à jour le rendement en tâche de fond et exporte
    vers defi_yield_state.json pour le dashboard.
    """
    if not _SWARM_DEFI_AVAILABLE:
        return

    while True:
        try:
            await asyncio.sleep(60)
            update_yield_and_export()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning("defi_yield_loop error: %s", e)


async def main() -> None:
    """Master Loop : orchestration 24h/24."""
    global _main_task, _loop

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except (ValueError, OSError, AttributeError):
            pass

    log.info("=" * 60)
    log.info("NEXUS CAPITAL - Master Loop starting")
    log.info("=" * 60)

    try:
        ok = await alert_startup()
        if ok:
            log.info("Telegram startup message sent")
        else:
            log.warning("Telegram startup failed (check TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID in .env)")
    except Exception as e:
        log.warning("Telegram startup error: %s", e)

    # Initialiser l'état DeFi Yield au démarrage
    if _SWARM_DEFI_AVAILABLE:
        try:
            update_yield_and_export()
            log.info("DeFi Yield state initialized")
        except Exception as e:
            log.warning("DeFi Yield init: %s", e)

    _loop = asyncio.get_running_loop()
    _main_task = asyncio.current_task()
    assert _main_task is not None
    set_uptime_start()

    # TP/SL monitor (shared OrderManager instance)
    from execution.order_manager import OrderManager
    _order_manager = OrderManager()

    # Chaque tâche: passer la FONCTION, pas la coroutine. Factory appelée à chaque restart.
    tasks = [
        asyncio.create_task(run_task_with_restart(run_scanner_ws, task_name="scanner")),
        asyncio.create_task(run_task_with_restart(run_telegram_poller, task_name="telegram_poller")),
        asyncio.create_task(run_task_with_restart(_swarm_loop, task_name="swarm")),
        asyncio.create_task(run_task_with_restart(_auto_trade_loop, task_name="autotrade")),
        asyncio.create_task(run_task_with_restart(_defi_yield_loop, task_name="defi_yield")),
        asyncio.create_task(run_task_with_restart(_anti_sybil_loop, task_name="antisybil")),
        asyncio.create_task(run_task_with_restart(_order_manager.start_monitor_loop, task_name="tpsl")),
        asyncio.create_task(run_task_with_restart(_copy_trader_loop, task_name="copy_trader")),
    ]
    log.info("Master Loop running: Scanner | Telegram | Swarm | Auto-Trade | DeFi Yield | Anti-Sybil | TP/SL | Copy")

    try:
        # return_exceptions=True: une exception ne tue pas les autres tâches
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                log.exception("Task %d failed: %s", i, r)
    except asyncio.CancelledError:
        log.info("Shutdown requested, cancelling tasks...")
        for t in tasks:
            t.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=10.0,
            )
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        log.info("NEXUS CAPITAL - Master Loop stopped gracefully.")
    except Exception as e:
        log.exception("NEXUS CAPITAL fatal error: %s", e)
        for t in tasks:
            t.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=5.0,
            )
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
    finally:
        sys.exit(0)
