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
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

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


def _settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Thresholds", callback_data="settings_thresholds"),
            InlineKeyboardButton("💰 Capital", callback_data="settings_capital"),
        ],
        [
            InlineKeyboardButton("🔁 Simulation", callback_data="settings_toggle_sim"),
            InlineKeyboardButton("🤖 Auto-Trade", callback_data="settings_autotrade"),
        ],
        [InlineKeyboardButton("⚙️ Avancé", callback_data="settings_advanced")],
        [InlineKeyboardButton("◀ Retour", callback_data="menu_back")],
    ])


def _settings_autotrade_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Toggle ON/OFF", callback_data="settings_autotrade_toggle")],
        [InlineKeyboardButton("Max positions", callback_data="settings_max_positions")],
        [InlineKeyboardButton("Drawdown limit %", callback_data="settings_drawdown")],
        [InlineKeyboardButton("Confirm BUY (yes/no)", callback_data="settings_confirm_buy")],
        [InlineKeyboardButton("◀ Retour", callback_data="btn_settings")],
    ])


def _settings_advanced_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Categories blacklist", callback_data="settings_categories")],
        [InlineKeyboardButton("Min/Max days resolution", callback_data="settings_days_resolution")],
        [InlineKeyboardButton("Keywords blacklist", callback_data="settings_keywords")],
        [InlineKeyboardButton("Reinvest %", callback_data="settings_reinvest")],
        [InlineKeyboardButton("◀ Retour", callback_data="btn_settings")],
    ])


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
    """Real USDC balance from Polymarket + open positions from SQLite."""
    lines = ["<b>💰 PORTFOLIO</b>\n"]
    try:
        # Fetch real USDC balance from Polymarket data API
        relayer_addr = os.getenv("RELAYER_API_KEY_ADDRESS")
        if relayer_addr:
            import httpx
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(
                        f"https://data-api.polymarket.com/value?user={relayer_addr}"
                    )
                    if r.status_code == 200:
                        data = r.json()
                        if isinstance(data, list) and data:
                            val = data[0].get("value", 0)
                            lines.append(f"💵 USDC: <b>{float(val):,.2f}</b>\n")
                        elif isinstance(data, dict):
                            val = data.get("value", 0)
                            lines.append(f"💵 USDC: <b>{float(val):,.2f}</b>\n")
            except Exception as e:
                log.debug("Polymarket value API: %s", e)

        from monitoring.trade_logger import trade_logger
        positions = trade_logger.get_positions()
        if not positions:
            if len(lines) <= 1:
                return "<b>💰 PORTFOLIO</b>\n\nAucune position ouverte."
            lines.append("Aucune position ouverte.")
            return "\n".join(lines)
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
    """Current config: capital, simulation, auto-trade, thresholds."""
    try:
        from config.settings import settings

        cap = getattr(settings, "POLYMARKET_CAPITAL_USD", 1000)
        sim = os.getenv("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")
        at = os.getenv("AUTO_TRADE_ENABLED", "false").lower() in ("true", "1", "yes")
        kelly = getattr(settings, "KELLY_FRACTION_CAP", 0.25) * 100
        min_edge = getattr(settings, "MIN_EDGE_PCT", 0.02) * 100
        max_pos = os.getenv("AUTO_TRADE_MAX_POSITIONS", "3")
        drawdown = os.getenv("AUTO_TRADE_DAILY_DRAWDOWN_LIMIT", "20")
        confirm = os.getenv("AUTO_TRADE_CONFIRM_BUY", "true").lower() in ("true", "1", "yes")
        return (
            "<b>⚙️ SETTINGS</b>\n\n"
            f"Capital: <b>{cap:,.0f} USD</b>\n"
            f"Simulation: <b>{'ON' if sim else 'OFF'}</b>\n"
            f"Auto-Trade: <b>{'ON' if at else 'OFF'}</b>\n"
            f"Max positions: {max_pos} | Drawdown: {drawdown}%\n"
            f"Confirm BUY: <b>{'Oui' if confirm else 'Non'}</b>\n"
            f"Kelly: {kelly:.1f}% | Edge min: {min_edge:.1f}%\n"
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


async def handle_settings_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text input when awaiting settings value (thresholds or capital)."""
    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return
    text = (update.message.text or "").strip()
    if not text:
        return

    from monitoring.env_config import set_env_value, set_env_values

    if awaiting == "thresholds":
        parts = text.split()
        if len(parts) >= 4:
            try:
                min_edge, min_ev, volume, liquidity = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
                ok = set_env_values({
                    "MIN_EDGE_THRESHOLD": min_edge,
                    "MIN_EV_THRESHOLD": min_ev,
                    "MIN_MARKET_VOLUME": volume,
                    "MIN_LIQUIDITY": liquidity,
                })
            except (ValueError, TypeError):
                ok = False
        else:
            ok = False
        context.user_data.pop("awaiting", None)
        status = "✅ Seuils mis à jour" if ok else "❌ Format invalide. Envoie: min_edge min_ev volume liquidity"
        await update.message.reply_text(
            f"{status}\n\n{_get_settings_text()}",
            parse_mode="HTML",
            reply_markup=_settings_keyboard(),
        )
        return

    if awaiting == "capital":
        try:
            val = float(text.replace(",", "."))
            if val > 0:
                ok = set_env_value("TOTAL_CAPITAL", int(val) if val == int(val) else val)
            else:
                ok = False
        except (ValueError, TypeError):
            ok = False
        context.user_data.pop("awaiting", None)
        status = "✅ Capital mis à jour" if ok else "❌ Valeur invalide"
        await update.message.reply_text(f"{status}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_keyboard())
        return

    if awaiting == "max_positions":
        try:
            val = int(text)
            ok = set_env_value("AUTO_TRADE_MAX_POSITIONS", max(1, min(val, 20))) if 1 <= val <= 20 else False
        except (ValueError, TypeError):
            ok = False
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"{'✅' if ok else '❌'}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_autotrade_keyboard())
        return

    if awaiting == "drawdown":
        try:
            val = float(text.replace(",", "."))
            ok = set_env_value("AUTO_TRADE_DAILY_DRAWDOWN_LIMIT", max(1, min(val, 100))) if 1 <= val <= 100 else False
        except (ValueError, TypeError):
            ok = False
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"{'✅' if ok else '❌'}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_autotrade_keyboard())
        return

    if awaiting == "categories":
        parts = [x.strip().lower() for x in text.split(",") if x.strip()]
        valid = {"sport", "politique", "crypto", "finance", "autre"}
        filtered = [p for p in parts if p in valid]
        ok = set_env_value("AUTO_TRADE_CATEGORIES_BLACKLIST", ",".join(filtered))
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"{'✅' if ok else '❌'}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_advanced_keyboard())
        return

    if awaiting == "days_resolution":
        parts = text.split()
        if len(parts) >= 2:
            try:
                min_d, max_d = int(parts[0]), int(parts[1])
                ok1 = set_env_value("AUTO_TRADE_MIN_DAYS_RESOLUTION", max(0, min_d))
                ok2 = set_env_value("AUTO_TRADE_MAX_DAYS_RESOLUTION", max(min_d, max_d))
                ok = ok1 and ok2
            except (ValueError, TypeError):
                ok = False
        else:
            ok = False
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"{'✅' if ok else '❌'}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_advanced_keyboard())
        return

    if awaiting == "reinvest":
        try:
            val = float(text.replace(",", "."))
            ok = set_env_value("AUTO_TRADE_REINVEST_PCT", max(0, min(100, int(val)))) if 0 <= val <= 100 else False
        except (ValueError, TypeError):
            ok = False
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"{'✅' if ok else '❌'}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_advanced_keyboard())
        return

    if awaiting == "keywords":
        parts = [x.strip().lower() for x in text.split(",") if x.strip()]
        ok = set_env_value("AUTO_TRADE_KEYWORDS_BLACKLIST", ",".join(parts))
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"{'✅' if ok else '❌'}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_advanced_keyboard())
        return


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
        await edit(text, _settings_keyboard())
        return

    # Settings submenu
    if data == "settings_thresholds":
        context.user_data["awaiting"] = "thresholds"
        await edit(
            "<b>📊 Edit Thresholds</b>\n\n"
            "Envoie 4 valeurs séparées par des espaces :\n"
            "<code>min_edge min_ev volume liquidity</code>\n\n"
            "Ex. <code>5.0 20 10000 1000</code>",
            _back_keyboard(),
        )
        return

    if data == "settings_capital":
        context.user_data["awaiting"] = "capital"
        await edit(
            "<b>💰 Edit Capital</b>\n\n"
            "Envoie le nouveau capital en USD (ex. <code>100</code>)",
            _back_keyboard(),
        )
        return

    if data == "settings_toggle_sim":
        from monitoring.env_config import set_env_value
        sim = os.getenv("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")
        new_val = not sim
        ok = set_env_value("SIMULATION_MODE", str(new_val).lower())
        text = _get_settings_text()
        status = "✅ Simulation " + ("ON" if new_val else "OFF") if ok else "❌ Erreur .env"
        await edit(f"{status}\n\n{text}", _settings_keyboard())
        return

    if data == "settings_autotrade":
        text = _get_settings_text() + "\n<i>Auto-Trade: STRONG_BUY→exécute | BUY→confirmation 30min</i>"
        await edit(text, _settings_autotrade_keyboard())
        return

    if data == "settings_autotrade_toggle":
        from monitoring.env_config import set_env_value
        at = os.getenv("AUTO_TRADE_ENABLED", "false").lower() in ("true", "1", "yes")
        ok = set_env_value("AUTO_TRADE_ENABLED", str(not at).lower())
        status = "✅ Auto-Trade " + ("ON" if not at else "OFF") if ok else "❌ Erreur"
        await edit(f"{status}\n\n{_get_settings_text()}", _settings_autotrade_keyboard())
        return

    if data == "settings_max_positions":
        context.user_data["awaiting"] = "max_positions"
        await edit("Envoie le nombre max de positions (ex. <code>3</code>)", _settings_autotrade_keyboard())
        return

    if data == "settings_drawdown":
        context.user_data["awaiting"] = "drawdown"
        await edit("Envoie la limite drawdown % (ex. <code>20</code>)", _settings_autotrade_keyboard())
        return

    if data == "settings_confirm_buy":
        from monitoring.env_config import set_env_value
        cur = os.getenv("AUTO_TRADE_CONFIRM_BUY", "true").lower() in ("true", "1", "yes")
        ok = set_env_value("AUTO_TRADE_CONFIRM_BUY", str(not cur).lower())
        status = "✅ Confirm BUY: " + ("Non" if cur else "Oui") if ok else "❌ Erreur"
        await edit(f"{status}\n\n{_get_settings_text()}", _settings_autotrade_keyboard())
        return

    if data == "settings_advanced":
        cats = os.getenv("AUTO_TRADE_CATEGORIES_BLACKLIST", "")
        min_d = os.getenv("AUTO_TRADE_MIN_DAYS_RESOLUTION", "1")
        max_d = os.getenv("AUTO_TRADE_MAX_DAYS_RESOLUTION", "365")
        kw = os.getenv("AUTO_TRADE_KEYWORDS_BLACKLIST", "")
        reinv = os.getenv("AUTO_TRADE_REINVEST_PCT", "0")
        text = f"<b>Avancé</b>\n\nCategories: {cats or '(vide)'}\nMin/Max days: {min_d}-{max_d}\nKeywords: {kw or '(vide)'}\nReinvest: {reinv}%"
        await edit(text, _settings_advanced_keyboard())
        return

    if data == "settings_categories":
        context.user_data["awaiting"] = "categories"
        await edit("Envoie les catégories à exclure, séparées par des virgules:\n<code>sport,politique,crypto,finance,autre</code>", _settings_advanced_keyboard())
        return

    if data == "settings_days_resolution":
        context.user_data["awaiting"] = "days_resolution"
        await edit("Envoie min et max jours (ex. <code>1 30</code>)", _settings_advanced_keyboard())
        return

    if data == "settings_reinvest":
        context.user_data["awaiting"] = "reinvest"
        await edit("Envoie le % de gains à réinvestir (0-100, ex. <code>50</code>)", _settings_advanced_keyboard())
        return

    # Auto-trade confirm/ignore
    if data.startswith("autotrade_confirm_"):
        sid = data.replace("autotrade_confirm_", "")
        from monitoring.auto_trade import get_pending_confirm, remove_pending_confirm, execute_signal
        sig = get_pending_confirm(sid)
        if not sig:
            await edit("⏱ Confirmation expirée (>30min)")
            return
        await edit("⏳ Exécution...", None)
        order_id = await execute_signal(sig)
        remove_pending_confirm(sid)
        await edit(f"✅ Ordre exécuté | ID: {order_id}" if order_id else "❌ Échec", _main_keyboard())
        return

    if data.startswith("autotrade_ignore_"):
        sid = data.replace("autotrade_ignore_", "")
        from monitoring.auto_trade import remove_pending_confirm
        remove_pending_confirm(sid)
        await edit("❌ Signal ignoré", _main_keyboard())
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
    """Delete webhook and flush pending updates to avoid 409 conflict."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.get(
                f"https://api.telegram.org/bot{token}/deleteWebhook",
                params={"drop_pending_updates": True},
            )
            await client.post(
                f"https://api.telegram.org/bot{token}/getUpdates",
                json={"offset": -1, "timeout": 0},
            )
        return True
    except Exception:
        return False


def _is_conflict_error(exc: BaseException) -> bool:
    """Check if exception (or its chain) is a Telegram 409 Conflict."""
    try:
        from telegram.error import Conflict
        if isinstance(exc, Conflict):
            return True
    except ImportError:
        pass
    return "409" in str(exc) or "Conflict" in str(exc)


async def run_telegram_poller() -> None:
    """Long-polling loop with 409 Conflict auto-recovery and exponential backoff."""
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        log.info("Telegram token non configuré, poller désactivé")
        return

    for _log in ("telegram", "telegram.ext"):
        logging.getLogger(_log).setLevel(logging.ERROR)

    base_delay = 5.0
    max_delay = 300.0
    delay = base_delay

    try:
        while True:
            app = None
            poll_task = None
            try:
                await close_telegram_session(token)
                await asyncio.sleep(2)

                app = Application.builder().token(token).build()
                app.add_handler(CommandHandler("start", cmd_start))
                app.add_handler(CallbackQueryHandler(callback_handler))
                app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings_text))

                await app.initialize()
                await app.start()
                poll_task = asyncio.create_task(app.updater.start_polling(drop_pending_updates=True))

                log.info("Telegram poller démarré (python-telegram-bot)")
                delay = base_delay

                while poll_task and not poll_task.done():
                    await asyncio.sleep(10)

                if poll_task and poll_task.done():
                    exc = poll_task.exception()
                    if exc is not None:
                        raise exc
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if _is_conflict_error(e):
                    log.info("Telegram 409 Conflict — purging queue and retrying in 5s")
                    await close_telegram_session(token)
                    await asyncio.sleep(5)
                    delay = base_delay
                else:
                    log.debug("Telegram poller error (retry in %.0fs): %s", delay, e)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, max_delay)
            finally:
                if poll_task and not poll_task.done():
                    poll_task.cancel()
                    try:
                        await asyncio.wait_for(poll_task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                if app:
                    try:
                        await app.updater.stop()
                        await app.stop()
                        await app.shutdown()
                    except Exception:
                        pass
    except asyncio.CancelledError:
        log.info("Telegram poller arrêté")
        raise
