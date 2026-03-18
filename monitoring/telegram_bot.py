"""
NEXUS CAPITAL - Telegram Bot (python-telegram-bot)
Pro terminal UX — Gold & Black, data first, zero blabla.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

log = logging.getLogger(__name__)

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("'\"").strip()
            if k and v:
                os.environ.setdefault(k, v)

LINE = "━━━━━━━━━━━━━━━━━━━━━"


# ══════════════════════════════════════════════
# KEYBOARDS
# ══════════════════════════════════════════════

def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Portfolio", callback_data="btn_portfolio"),
            InlineKeyboardButton("🔍 Scan", callback_data="btn_scan"),
        ],
        [
            InlineKeyboardButton("🤖 Agents", callback_data="btn_agents"),
            InlineKeyboardButton("📈 BTC Markets", callback_data="btn_btc"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="btn_settings"),
            InlineKeyboardButton("📡 Alpha Stream", callback_data="btn_alpha"),
        ],
    ])


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu_back")]])


def _portfolio_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Positions", callback_data="portfolio_positions"),
            InlineKeyboardButton("📜 Historique", callback_data="portfolio_history"),
        ],
        [InlineKeyboardButton("🔙 Menu", callback_data="menu_back")],
    ])


def _scan_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="btn_scan"),
            InlineKeyboardButton("🔙 Menu", callback_data="menu_back"),
        ],
    ])


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
        [InlineKeyboardButton("🔙 Menu", callback_data="menu_back")],
    ])


def _settings_autotrade_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Toggle ON/OFF", callback_data="settings_autotrade_toggle")],
        [InlineKeyboardButton("Max positions", callback_data="settings_max_positions")],
        [InlineKeyboardButton("Drawdown limit %", callback_data="settings_drawdown")],
        [InlineKeyboardButton("Confirm BUY (yes/no)", callback_data="settings_confirm_buy")],
        [InlineKeyboardButton("🔙 Settings", callback_data="btn_settings")],
    ])


def _settings_advanced_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Categories blacklist", callback_data="settings_categories")],
        [InlineKeyboardButton("Min/Max days resolution", callback_data="settings_days_resolution")],
        [InlineKeyboardButton("Keywords blacklist", callback_data="settings_keywords")],
        [InlineKeyboardButton("Reinvest %", callback_data="settings_reinvest")],
        [InlineKeyboardButton("🔙 Settings", callback_data="btn_settings")],
    ])


# ══════════════════════════════════════════════
# TEXT GENERATORS — Pro Terminal Style
# ══════════════════════════════════════════════

def _status_line() -> str:
    sim = os.getenv("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")
    return "🟡 SIMULATION" if sim else "🟢 LIVE"


def _get_capital() -> float:
    try:
        from config.settings import settings
        return settings.POLYMARKET_CAPITAL_USD
    except Exception:
        return 0.0


def _get_market_count() -> int:
    try:
        p = Path(__file__).resolve().parent.parent / "paperclip_pending_signals.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get("market_count", 0)
    except Exception:
        pass
    return 0


async def _get_start_text() -> str:
    cap = _get_capital()
    status = _status_line()
    return (
        f"⚡ <b>NEXUS CAPITAL</b>\n"
        f"<i>Prediction Market Intelligence</i>\n"
        f"\n{LINE}\n"
        f"🟡 STATUS   ● {status}\n"
        f"💰 CAPITAL  <b>${cap:,.2f}</b> USDC\n"
        f"{LINE}"
    )


async def _get_scan_text() -> str:
    try:
        from data.polymarket_client import PolymarketClient
        from core.edge_engine import EdgeEngine
        from core.scanner import MarketScanner

        pm = PolymarketClient()
        engine = EdgeEngine()
        scanner = MarketScanner(pm, engine, on_signal=None)
        signals = await scanner._scan_once()
        await pm.close()

        header = (
            f"🔍 <b>MARKET SCANNER</b>\n"
            f"{LINE}\n"
        )

        if not signals:
            return (
                f"{header}"
                f"📡 Scan en cours...\n"
                f"⚠️ Aucun edge ≥ seuil détecté\n"
                f"{LINE}"
            )

        lines = [
            f"{header}"
            f"🟢 <b>{len(signals)}</b> signal(s) détecté(s)\n"
        ]
        for i, s in enumerate(signals[:5], 1):
            q = (s.metadata.get("question") or s.market_id[:30])[:50]
            strength = "⚡" if s.signal_strength == "STRONG_BUY" else "🟢"
            lines.append(
                f"{strength} <b>{s.side}</b> │ Edge <b>{s.edge_pct*100:.1f}%</b> │ Kelly {s.kelly_fraction*100:.1f}%\n"
                f"   <i>{q}</i>"
            )
        lines.append(f"\n{LINE}")
        return "\n".join(lines)
    except Exception as e:
        log.exception("Scan failed: %s", e)
        return f"🔍 <b>MARKET SCANNER</b>\n{LINE}\n❌ Erreur: {e}"


async def _get_portfolio_text() -> str:
    header = f"💼 <b>PORTFOLIO</b>\n{LINE}\n"
    lines = [header]
    try:
        relayer_addr = os.getenv("RELAYER_API_KEY_ADDRESS")
        balance = 0.0
        if relayer_addr:
            import httpx
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(f"https://data-api.polymarket.com/value?user={relayer_addr}")
                    if r.status_code == 200:
                        data = r.json()
                        if isinstance(data, list) and data:
                            balance = float(data[0].get("value", 0))
                        elif isinstance(data, dict):
                            balance = float(data.get("value", 0))
            except Exception:
                pass

        from monitoring.trade_logger import trade_logger
        positions = trade_logger.get_positions()
        trades = trade_logger.get_recent_trades(limit=100)

        today = datetime.now(timezone.utc).date().isoformat()
        pnl_today = sum(float(t.get("pnl") or 0) for t in trades if str(t.get("created_at", ""))[:10] == today)
        cap = _get_capital() or 1
        pnl_pct = (pnl_today / cap * 100) if cap > 0 else 0

        wins = sum(1 for t in trades if float(t.get("pnl") or 0) > 0)
        total_closed = sum(1 for t in trades if t.get("status") in ("FILLED", "CLOSED"))
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0

        pnl_sign = "+" if pnl_today >= 0 else ""
        lines.append(
            f"💰 Balance    <b>${balance:,.2f}</b> USDC\n"
            f"📈 P&amp;L Today  <b>{pnl_sign}${pnl_today:,.2f}</b> ({pnl_sign}{pnl_pct:.1f}%)\n"
            f"🎯 Positions  <b>{len(positions)}</b> ouvertes\n"
            f"✅ Win Rate   <b>{win_rate:.0f}%</b> ({wins}/{total_closed})\n"
            f"{LINE}"
        )
        return "\n".join(lines)
    except Exception as e:
        log.exception("Portfolio failed: %s", e)
        return f"{header}❌ Erreur: {e}"


async def _get_positions_detail() -> str:
    try:
        from monitoring.trade_logger import trade_logger
        positions = trade_logger.get_positions()
        if not positions:
            return f"📋 <b>POSITIONS</b>\n{LINE}\nAucune position ouverte.\n{LINE}"
        lines = [f"📋 <b>POSITIONS</b> ({len(positions)})\n{LINE}\n"]
        for p in positions[:10]:
            mid = (p.get("market_id") or "")[:20]
            lines.append(
                f"▸ <code>{mid}...</code>\n"
                f"  {p.get('outcome','?')} │ ${float(p.get('size', 0)):,.2f} @ {float(p.get('avg_price', 0)):.2%}"
            )
        lines.append(f"\n{LINE}")
        return "\n".join(lines)
    except Exception as e:
        return f"📋 <b>POSITIONS</b>\n{LINE}\n❌ {e}"


async def _get_history_text() -> str:
    try:
        from monitoring.trade_logger import trade_logger
        trades = trade_logger.get_recent_trades(limit=10)
        if not trades:
            return f"📜 <b>HISTORIQUE</b>\n{LINE}\nAucun trade enregistré.\n{LINE}"
        lines = [f"📜 <b>HISTORIQUE</b> (derniers {len(trades)})\n{LINE}\n"]
        for t in trades:
            pnl = float(t.get("pnl") or 0)
            icon = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
            side = t.get("outcome", "?")
            lines.append(f"{icon} {side} │ PnL ${pnl:+,.2f} │ {str(t.get('created_at',''))[:10]}")
        lines.append(f"\n{LINE}")
        return "\n".join(lines)
    except Exception as e:
        return f"📜 <b>HISTORIQUE</b>\n{LINE}\n❌ {e}"


async def _get_agents_text() -> str:
    header = f"🤖 <b>AI AGENTS DEBATE</b>\n{LINE}\n"
    try:
        p = Path(__file__).resolve().parent.parent / "ai_debates_log.json"
        if not p.exists():
            return (
                f"{header}"
                f"En attente d'un signal fort...\n"
                f"<i>Les agents s'activent quand edge ≥ 3%</i>\n"
                f"{LINE}"
            )
        data = json.loads(p.read_text(encoding="utf-8"))
        latest = data.get("latest_swarm", {})
        debates = data.get("debates", [])

        if not latest and not debates:
            return (
                f"{header}"
                f"En attente d'un signal fort...\n"
                f"<i>Les agents s'activent quand edge ≥ 3%</i>\n"
                f"{LINE}"
            )

        lines = [header]
        if latest:
            approved = latest.get("approved", False)
            verdict = "✅ APPROVED" if approved else "❌ REJECTED"
            q = str(latest.get("question", latest.get("market_id", "—")))[:50]
            lines.append(
                f"📌 <b>DERNIER DÉBAT</b>\n"
                f"Market: <i>{q}</i>\n"
                f"Side: <b>{latest.get('side','?')}</b> │ "
                f"YES: <b>{latest.get('pct_yes', 0):.0f}%</b> │ "
                f"Verdict: <b>{verdict}</b>\n"
            )
        if debates:
            last = debates[-1]
            msg = str(last.get("message", last.get("content", "")))[:180]
            role = last.get("role", last.get("agent", "Agent"))
            lines.append(f"💬 <b>{role}</b>: <i>{msg}</i>")
        lines.append(f"\n{LINE}")
        return "\n".join(lines)
    except Exception as e:
        return f"{header}❌ {e}"


async def _get_btc_text() -> str:
    header = f"📈 <b>BTC / CRYPTO MARKETS</b>\n{LINE}\n"
    try:
        from data.polymarket_client import PolymarketClient
        pm = PolymarketClient()
        markets = await pm.get_markets(limit=100)
        await pm.close()
        btc = [
            m for m in markets
            if any(kw in (m.get("question") or "").lower() for kw in ("btc", "bitcoin", "crypto", "ethereum", "eth"))
        ]
        if not btc:
            return f"{header}Aucun marché crypto actif.\n{LINE}"
        lines = [f"{header}"]
        for m in btc[:8]:
            q = (m.get("question") or "")[:50]
            prices = m.get("outcomePrices") or "[]"
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices)
                except Exception:
                    prices = []
            yes_p = float(prices[0]) * 100 if isinstance(prices, list) and prices else 0
            lines.append(f"▸ <b>{yes_p:.0f}%</b> YES │ <i>{q}</i>")
        if len(btc) > 8:
            lines.append(f"\n+{len(btc)-8} autres marchés")
        lines.append(f"\n{LINE}")
        return "\n".join(lines)
    except Exception as e:
        return f"{header}❌ {e}"


async def _get_alpha_text() -> str:
    header = f"📡 <b>ALPHA STREAM</b>\n{LINE}\n"
    try:
        p = Path(__file__).resolve().parent.parent / "ai_debates_log.json"
        if not p.exists():
            return f"{header}<i>En attente de signaux...</i>\n{LINE}"
        data = json.loads(p.read_text(encoding="utf-8"))
        stream = data.get("alpha_stream", data.get("debates", []))
        if not stream:
            return f"{header}<i>En attente de signaux...</i>\n{LINE}"
        lines = [header]
        for item in stream[-5:]:
            msg = str(item.get("message", item.get("content", "")))[:100]
            ts = str(item.get("timestamp", item.get("created_at", "")))[:16]
            lines.append(f"▸ [{ts}] {msg}")
        lines.append(f"\n{LINE}")
        return "\n".join(lines)
    except Exception as e:
        return f"{header}❌ {e}"


def _get_settings_text() -> str:
    try:
        from config.settings import settings
        cap = getattr(settings, "POLYMARKET_CAPITAL_USD", 1000)
        sim = os.getenv("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")
        try:
            from monitoring.telegram_wealth_manager import get_auto_trade
            at = get_auto_trade()
        except Exception:
            at = os.getenv("AUTO_TRADE_ENABLED", "false").lower() in ("true", "1", "yes")
        kelly = getattr(settings, "KELLY_FRACTION_CAP", 0.25) * 100
        min_edge = getattr(settings, "MIN_EDGE_PCT", 0.02) * 100
        max_pos = os.getenv("AUTO_TRADE_MAX_POSITIONS", "3")
        drawdown = os.getenv("AUTO_TRADE_DAILY_DRAWDOWN_LIMIT", "20")
        confirm = os.getenv("AUTO_TRADE_CONFIRM_BUY", "true").lower() in ("true", "1", "yes")
        return (
            f"⚙️ <b>SETTINGS</b>\n"
            f"{LINE}\n"
            f"💰 Capital      <b>${cap:,.0f}</b>\n"
            f"🔁 Simulation   <b>{'ON' if sim else 'OFF'}</b>\n"
            f"🤖 Auto-Trade   <b>{'ON' if at else 'OFF'}</b>\n"
            f"📊 Max Pos      <b>{max_pos}</b> │ Drawdown <b>{drawdown}%</b>\n"
            f"✅ Confirm BUY  <b>{'YES' if confirm else 'NO'}</b>\n"
            f"📐 Kelly        <b>{kelly:.1f}%</b> │ Edge min <b>{min_edge:.1f}%</b>\n"
            f"{LINE}"
        )
    except Exception as e:
        return f"⚙️ <b>SETTINGS</b>\n{LINE}\n❌ {e}"


# ══════════════════════════════════════════════
# HANDLERS
# ══════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = await _get_start_text()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=_main_keyboard())


async def handle_settings_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
                    "MIN_EDGE_THRESHOLD": min_edge, "MIN_EV_THRESHOLD": min_ev,
                    "MIN_MARKET_VOLUME": volume, "MIN_LIQUIDITY": liquidity,
                })
            except (ValueError, TypeError):
                ok = False
        else:
            ok = False
        context.user_data.pop("awaiting", None)
        status = "✅ Seuils mis à jour" if ok else "❌ Format: min_edge min_ev volume liquidity"
        await update.message.reply_text(f"{status}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_keyboard())
        return

    if awaiting == "capital":
        try:
            val = float(text.replace(",", "."))
            ok = set_env_value("TOTAL_CAPITAL", int(val) if val == int(val) else val) if val > 0 else False
        except (ValueError, TypeError):
            ok = False
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"{'✅' if ok else '❌'}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_keyboard())
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
                ok = set_env_value("AUTO_TRADE_MIN_DAYS_RESOLUTION", max(0, min_d)) and set_env_value("AUTO_TRADE_MAX_DAYS_RESOLUTION", max(min_d, max_d))
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
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    async def edit(text: str, kb: InlineKeyboardMarkup | None = None):
        await q.edit_message_text(text=text, parse_mode="HTML", reply_markup=kb)

    # ── Main menu ──
    if data == "menu_back":
        text = await _get_start_text()
        await edit(text, _main_keyboard())
        return

    if data == "btn_scan":
        await edit(f"🔍 <b>SCANNING...</b>\n{LINE}", None)
        text = await _get_scan_text()
        await edit(text, _scan_keyboard())
        return

    if data == "btn_portfolio":
        await edit(f"💼 <b>LOADING...</b>\n{LINE}", None)
        text = await _get_portfolio_text()
        await edit(text, _portfolio_keyboard())
        return

    if data == "portfolio_positions":
        await edit(f"📋 <b>LOADING...</b>\n{LINE}", None)
        text = await _get_positions_detail()
        await edit(text, _portfolio_keyboard())
        return

    if data == "portfolio_history":
        await edit(f"📜 <b>LOADING...</b>\n{LINE}", None)
        text = await _get_history_text()
        await edit(text, _portfolio_keyboard())
        return

    if data == "btn_agents":
        await edit(f"🤖 <b>LOADING...</b>\n{LINE}", None)
        text = await _get_agents_text()
        await edit(text, _back_keyboard())
        return

    if data == "btn_btc":
        await edit(f"📈 <b>LOADING...</b>\n{LINE}", None)
        text = await _get_btc_text()
        await edit(text, _back_keyboard())
        return

    if data == "btn_alpha":
        await edit(f"📡 <b>LOADING...</b>\n{LINE}", None)
        text = await _get_alpha_text()
        await edit(text, _back_keyboard())
        return

    # ── Settings ──
    if data == "btn_settings":
        await edit(_get_settings_text(), _settings_keyboard())
        return

    if data == "settings_thresholds":
        context.user_data["awaiting"] = "thresholds"
        await edit(
            f"📊 <b>THRESHOLDS</b>\n{LINE}\n"
            "4 valeurs séparées par des espaces :\n"
            "<code>min_edge min_ev volume liquidity</code>\n\n"
            "Ex: <code>5.0 20 1000 100</code>",
            _back_keyboard(),
        )
        return

    if data == "settings_capital":
        context.user_data["awaiting"] = "capital"
        await edit(f"💰 <b>CAPITAL</b>\n{LINE}\nEnvoie le montant en USD\nEx: <code>100</code>", _back_keyboard())
        return

    if data == "settings_toggle_sim":
        from monitoring.env_config import set_env_value
        sim = os.getenv("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")
        ok = set_env_value("SIMULATION_MODE", str(not sim).lower())
        await edit(_get_settings_text(), _settings_keyboard())
        return

    if data == "settings_autotrade":
        text = _get_settings_text() + "\n<i>STRONG_BUY → exécution immédiate\nBUY → confirmation 30min</i>"
        await edit(text, _settings_autotrade_keyboard())
        return

    if data == "settings_autotrade_toggle":
        try:
            from monitoring.telegram_wealth_manager import get_auto_trade, set_auto_trade
            current = get_auto_trade()
            set_auto_trade(not current)
        except ImportError:
            from monitoring.env_config import set_env_value
            at = os.getenv("AUTO_TRADE_ENABLED", "false").lower() in ("true", "1", "yes")
            set_env_value("AUTO_TRADE_ENABLED", str(not at).lower())
        await edit(_get_settings_text(), _settings_autotrade_keyboard())
        return

    if data == "settings_max_positions":
        context.user_data["awaiting"] = "max_positions"
        await edit(f"Max positions (1-20)\nEx: <code>3</code>", _settings_autotrade_keyboard())
        return

    if data == "settings_drawdown":
        context.user_data["awaiting"] = "drawdown"
        await edit(f"Drawdown limit % (1-100)\nEx: <code>20</code>", _settings_autotrade_keyboard())
        return

    if data == "settings_confirm_buy":
        from monitoring.env_config import set_env_value
        cur = os.getenv("AUTO_TRADE_CONFIRM_BUY", "true").lower() in ("true", "1", "yes")
        set_env_value("AUTO_TRADE_CONFIRM_BUY", str(not cur).lower())
        await edit(_get_settings_text(), _settings_autotrade_keyboard())
        return

    if data == "settings_advanced":
        cats = os.getenv("AUTO_TRADE_CATEGORIES_BLACKLIST", "") or "—"
        min_d = os.getenv("AUTO_TRADE_MIN_DAYS_RESOLUTION", "0")
        max_d = os.getenv("AUTO_TRADE_MAX_DAYS_RESOLUTION", "730")
        kw = os.getenv("AUTO_TRADE_KEYWORDS_BLACKLIST", "") or "—"
        reinv = os.getenv("AUTO_TRADE_REINVEST_PCT", "0")
        await edit(
            f"⚙️ <b>ADVANCED</b>\n{LINE}\n"
            f"🚫 Categories  {cats}\n"
            f"📅 Days        {min_d}–{max_d}\n"
            f"🔑 Keywords    {kw}\n"
            f"♻️ Reinvest    {reinv}%\n"
            f"{LINE}",
            _settings_advanced_keyboard(),
        )
        return

    if data == "settings_categories":
        context.user_data["awaiting"] = "categories"
        await edit("Catégories à exclure (virgules) :\n<code>sport,politique,crypto,finance,autre</code>", _settings_advanced_keyboard())
        return

    if data == "settings_days_resolution":
        context.user_data["awaiting"] = "days_resolution"
        await edit("Min et max jours :\n<code>0 730</code>", _settings_advanced_keyboard())
        return

    if data == "settings_reinvest":
        context.user_data["awaiting"] = "reinvest"
        await edit("% de gains à réinvestir (0-100) :\n<code>50</code>", _settings_advanced_keyboard())
        return

    if data == "settings_keywords":
        context.user_data["awaiting"] = "keywords"
        await edit("Mots-clés à exclure (virgules) :\n<code>war,nuclear</code>", _settings_advanced_keyboard())
        return

    # ── Auto-trade confirm/ignore ──
    if data.startswith("autotrade_confirm_"):
        sid = data.replace("autotrade_confirm_", "")
        from monitoring.auto_trade import get_pending_confirm, remove_pending_confirm, execute_signal
        sig = get_pending_confirm(sid)
        if not sig:
            await edit(f"⏱ Expiré (>30min)\n{LINE}")
            return
        await edit(f"⏳ Exécution...\n{LINE}", None)
        order_id = await execute_signal(sig)
        remove_pending_confirm(sid)
        await edit(
            f"✅ <b>ORDRE EXÉCUTÉ</b>\n{LINE}\nID: <code>{order_id}</code>" if order_id else f"❌ <b>ÉCHEC</b>\n{LINE}",
            _main_keyboard(),
        )
        return

    if data.startswith("autotrade_ignore_"):
        sid = data.replace("autotrade_ignore_", "")
        from monitoring.auto_trade import remove_pending_confirm
        remove_pending_confirm(sid)
        await edit(f"❌ Signal ignoré\n{LINE}", _main_keyboard())
        return

    # ── Wealth suggestion: approve / wait ──
    if data.startswith("approve_"):
        from monitoring.wealth_suggestions import get_suggestion, remove_suggestion
        sid = data.replace("approve_", "")
        sug = get_suggestion(sid)
        if not sug:
            await edit(f"⏱ Suggestion expirée\n{LINE}")
            return
        await edit(f"⏳ Exécution...\n{LINE}", None)
        try:
            from defi_yield_manager import execute_flash_withdraw
            from execution.order_manager import OrderManager, OrderConfig
            execute_flash_withdraw(float(sug.get("size_usd", 0)))
            om = OrderManager()
            cfg = OrderConfig(
                market_id=sug["market_id"], outcome=sug["outcome"],
                side=sug["side"], size_usd=float(sug["size_usd"]),
                limit_price=float(sug["limit_price"]),
            )
            order_id = await om.place_limit_order(cfg)
            remove_suggestion(sid)
            await edit(
                f"✅ <b>ORDRE EXÉCUTÉ</b>\n{LINE}\nID: <code>{order_id}</code>" if order_id else f"❌ Échec\n{LINE}",
                _main_keyboard(),
            )
        except Exception as e:
            log.exception("Approve error: %s", e)
            await edit(f"❌ {e}", _main_keyboard())
        return

    if data.startswith("wait_"):
        from monitoring.wealth_suggestions import remove_suggestion
        try:
            from defi_yield_manager import clear_pending_trade
            clear_pending_trade()
        except ImportError:
            pass
        remove_suggestion(data.replace("wait_", ""))
        await edit(f"⏸ En attente\n{LINE}", _main_keyboard())
        return


# ══════════════════════════════════════════════
# POLLER
# ══════════════════════════════════════════════

async def close_telegram_session(token: str) -> bool:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.get(f"https://api.telegram.org/bot{token}/deleteWebhook", params={"drop_pending_updates": True})
            await client.post(f"https://api.telegram.org/bot{token}/getUpdates", json={"offset": -1, "timeout": 0})
        return True
    except Exception:
        return False


def _is_conflict_error(exc: BaseException) -> bool:
    try:
        from telegram.error import Conflict
        if isinstance(exc, Conflict):
            return True
    except ImportError:
        pass
    return "409" in str(exc) or "Conflict" in str(exc)


async def run_telegram_poller() -> None:
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
