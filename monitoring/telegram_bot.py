"""
NEXUS CAPITAL - Telegram Bot (python-telegram-bot)
Inline keyboard: [📊 Scan] [💰 Portfolio] [🧠 Agents] [₿ BTC] [⚙️ Settings]
Each button updates the SAME message (no chat spam).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

log = logging.getLogger(__name__)

# Load .env
_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("'\"").strip()
            if k and v:
                os.environ.setdefault(k, v)


def _main_keyboard() -> InlineKeyboardMarkup:
    """Grid: [📊 Scan] [💰 Portfolio] [🧠 Agents] [₿ BTC] [⚙️ Settings]"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Scan", callback_data="btn_scan"),
            InlineKeyboardButton("💰 Portfolio", callback_data="btn_portfolio"),
        ],
        [
            InlineKeyboardButton("🧠 Agents", callback_data="btn_agents"),
            InlineKeyboardButton("₿ BTC", callback_data="btn_btc"),
        ],
        [InlineKeyboardButton("⚙️ Settings", callback_data="btn_settings")],
    ])


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀ Retour", callback_data="menu_back")]])


async def _get_scan_text() -> str:
    """Top 5 signals from Polymarket Gamma API + EdgeEngine."""
    try:
        from data.polymarket_client import PolymarketClient
        from core.edge_engine import EdgeEngine
        from core.scanner import MarketScanner

        pm = PolymarketClient()
        engine = EdgeEngine()
        scanner = MarketScanner(pm, engine, on_signal=None)
        signals = await scanner._scan_once()
        await pm.close()

        if not signals:
            return "<b>📊 SCAN</b>\n\nAucun signal détecté (edge &lt; seuil)."
        lines = [f"<b>📊 SCAN</b> – {len(signals)} signal(s)\n"]
        for s in signals[:5]:
            q = (s.metadata.get("question") or s.market_id[:40] or "—")[:60]
            lines.append(f"• {s.side} | Edge {s.edge_pct*100:.1f}% | Kelly {s.kelly_fraction*100:.1f}%\n  <i>{q}</i>")
        return "\n".join(lines)
    except Exception as e:
        log.exception("Scan failed: %s", e)
        return f"<b>📊 SCAN</b>\n\nErreur: {e}"


async def _get_portfolio_text() -> str:
    """Open positions from SQLite."""
    try:
        from monitoring.trade_logger import trade_logger

        positions = trade_logger.get_positions()
        if not positions:
            return "<b>💰 PORTFOLIO</b>\n\nAucune position ouverte."
        lines = ["<b>💰 PORTFOLIO</b>\n"]
        for p in positions:
            mid = (p.get("market_id") or "")[:25]
            lines.append(f"• {mid}... | {p.get('outcome')} | {p.get('size', 0):.2f} @ {p.get('avg_price', 0):.2%}")
        return "\n".join(lines)
    except Exception as e:
        log.exception("Portfolio failed: %s", e)
        return f"<b>💰 PORTFOLIO</b>\n\nErreur: {e}"


async def _get_agents_text() -> str:
    """Last debate summary from ai_debates_log.json."""
    try:
        p = Path(__file__).resolve().parent.parent / "ai_debates_log.json"
        if not p.exists():
            return "<b>🧠 AGENTS</b>\n\nAucun débat enregistré."
        data = json.loads(p.read_text(encoding="utf-8"))
        latest = data.get("latest_swarm", {})
        debates = data.get("debates", [])
        lines = ["<b>🧠 AGENTS – Dernier débat</b>\n"]
        if latest:
            lines.append(f"Market: {latest.get('market_id', '—')[:30]}...")
            lines.append(f"Side: {latest.get('side')} | YES: {latest.get('pct_yes', 0):.0f}%")
            lines.append(f"Verdict: {'✅ APPROUVÉ' if latest.get('approved') else '❌ REJETÉ'}")
        if debates:
            last = debates[-1]
            lines.append(f"\n<i>{last.get('message', last.get('content', ''))[:200]}</i>")
        return "\n".join(lines) if lines else "<b>🧠 AGENTS</b>\n\nAucun débat."
    except Exception as e:
        log.exception("Agents failed: %s", e)
        return f"<b>🧠 AGENTS</b>\n\nErreur: {e}"


async def _get_btc_text() -> str:
    """BTC markets from Polymarket."""
    try:
        from data.polymarket_client import PolymarketClient

        pm = PolymarketClient()
        markets = await pm.get_markets(limit=100)
        await pm.close()
        btc = [
            m for m in markets
            if "btc" in (m.get("question") or "").lower()
            or "bitcoin" in (m.get("question") or "").lower()
            or "crypto" in (m.get("question") or "").lower()
        ]
        if not btc:
            return "<b>₿ BTC</b>\n\nAucun marché BTC/crypto trouvé."
        lines = [f"<b>₿ BTC</b> – {len(btc)} marché(s)\n"]
        for m in btc[:5]:
            q = (m.get("question") or "")[:55]
            lines.append(f"• {q}...")
        if len(btc) > 5:
            lines.append(f"... +{len(btc)-5} autres")
        return "\n".join(lines)
    except Exception as e:
        log.exception("BTC failed: %s", e)
        return f"<b>₿ BTC</b>\n\nErreur: {e}"


def _get_settings_text() -> str:
    """Current config: capital, simulation mode, thresholds."""
    try:
        from config.settings import settings

        cap = getattr(settings, "POLYMARKET_CAPITAL_USD", 1000)
        sim = os.getenv("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")
        kelly = getattr(settings, "KELLY_FRACTION_CAP", 0.25) * 100
        min_edge = getattr(settings, "MIN_EDGE_PCT", 0.02) * 100
        return (
            "<b>⚙️ SETTINGS</b>\n\n"
            f"Capital: <b>{cap:,.0f} USD</b>\n"
            f"Simulation: <b>{'ON' if sim else 'OFF'}</b>\n"
            f"Kelly max: {kelly:.1f}%\n"
            f"Edge min: {min_edge:.1f}%\n"
        )
    except Exception as e:
        return f"<b>⚙️ SETTINGS</b>\n\nErreur: {e}"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ /start – show inline grid."""
    msg = (
        "<b>NEXUS CAPITAL</b>\n\n"
        "Choisis une action :"
    )
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=_main_keyboard())


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button clicks – UPDATE same message."""
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    chat_id = q.message.chat_id
    msg_id = q.message.message_id

    async def edit(text: str, kb: InlineKeyboardMarkup | None = None):
        await q.edit_message_text(text=text, parse_mode="HTML", reply_markup=kb)

    if data == "menu_back":
        await edit("<b>NEXUS CAPITAL</b>\n\nChoisis une action :", _main_keyboard())
        return

    if data == "btn_scan":
        await edit("⏳ Scan en cours...", None)
        text = await _get_scan_text()
        await edit(text, _back_keyboard())
        return

    if data == "btn_portfolio":
        await edit("⏳ Chargement...", None)
        text = await _get_portfolio_text()
        await edit(text, _back_keyboard())
        return

    if data == "btn_agents":
        await edit("⏳ Chargement...", None)
        text = await _get_agents_text()
        await edit(text, _back_keyboard())
        return

    if data == "btn_btc":
        await edit("⏳ Chargement...", None)
        text = await _get_btc_text()
        await edit(text, _back_keyboard())
        return

    if data == "btn_settings":
        text = _get_settings_text()
        await edit(text, _back_keyboard())
        return

    # Wealth suggestion: approve / wait
    if data.startswith("approve_"):
        from monitoring.wealth_suggestions import get_suggestion, remove_suggestion

        sid = data.replace("approve_", "")
        sug = get_suggestion(sid)
        if not sug:
            await edit("⏱ Suggestion expirée (>1h). Relance un scan.")
            return
        await edit("⏳ Exécution...", None)
        try:
            from defi_yield_manager import execute_flash_withdraw
            from execution.order_manager import OrderManager, OrderConfig

            execute_flash_withdraw(float(sug.get("size_usd", 0)))
            om = OrderManager()
            cfg = OrderConfig(
                market_id=sug["market_id"],
                outcome=sug["outcome"],
                side=sug["side"],
                size_usd=float(sug["size_usd"]),
                limit_price=float(sug["limit_price"]),
            )
            order_id = await om.place_limit_order(cfg)
            remove_suggestion(sid)
            await edit(f"✅ Ordre exécuté | ID: {order_id}"
                if order_id else "❌ Échec placement ordre")
        except Exception as e:
            log.exception("Approve error: %s", e)
            await edit(f"❌ Erreur: {e}")
        return

    if data.startswith("wait_"):
        from monitoring.wealth_suggestions import remove_suggestion
        try:
            from defi_yield_manager import clear_pending_trade
            clear_pending_trade()
        except ImportError:
            pass
        remove_suggestion(data.replace("wait_", ""))
        await edit("⏸ Suggestion mise en attente.")
        return


async def close_telegram_session(token: str) -> bool:
    """Delete webhook to avoid 409 conflict."""
    import httpx
    url = f"https://api.telegram.org/bot{token}/deleteWebhook"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params={"drop_pending_updates": True})
        return r.status_code == 200 and r.json().get("ok", False)
    except Exception:
        return False


async def run_telegram_poller() -> None:
    """Long-polling loop using python-telegram-bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        log.info("Telegram token non configuré, poller désactivé")
        return

    await close_telegram_session(token)
    await asyncio.sleep(1)

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))

    log.info("Telegram poller démarré (python-telegram-bot)")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # Run until cancelled
    try:
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        log.info("Telegram poller arrêté")
