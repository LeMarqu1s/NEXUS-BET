"""
NEXUS CAPITAL - Telegram Bot (python-telegram-bot)
Pro terminal UX — Gold & Black, data first, zero blabla.
Performance: response <1s, cache 60s, timeout 5s on all external calls.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

POLYGON_ADDRESS_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")
API_TIMEOUT = 5.0
CACHE_TTL = 60
_market_cache: dict[str, tuple[dict, float]] = {}

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
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
            InlineKeyboardButton("💼 Portfolio", callback_data="btn_portfolio"),
            InlineKeyboardButton("🔍 Scanner", callback_data="btn_scan"),
        ],
        [
            InlineKeyboardButton("🤖 AI Agents", callback_data="btn_agents"),
            InlineKeyboardButton("🐳 Whales", callback_data="btn_whales"),
        ],
        [
            InlineKeyboardButton("📈 BTC", callback_data="btn_btc"),
            InlineKeyboardButton("🤝 Referral", callback_data="btn_referral"),
        ],
        [InlineKeyboardButton("⚙️ Settings", callback_data="btn_settings")],
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


def _positions_keyboard() -> InlineKeyboardMarkup:
    """Clavier sous Portfolio pour revenir au menu Portfolio."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Portfolio", callback_data="btn_portfolio")]])


def _exit_confirm_keyboard() -> InlineKeyboardMarkup:
    """Boutons Confirmer / Annuler pour exit d'une position."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmer", callback_data="exit_confirm"),
            InlineKeyboardButton("❌ Annuler", callback_data="exit_cancel"),
        ],
    ])


def _wallet_confirm_keyboard(address: str) -> InlineKeyboardMarkup:
    """Boutons Ajouter / Annuler pour wallet détecté."""
    addr = (address or "").strip()[:42]
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Ajouter au monitoring", callback_data=f"wallet_add_{addr}"),
            InlineKeyboardButton("❌ Annuler", callback_data="wallet_cancel"),
        ],
    ])


def _scan_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="btn_scan"),
            InlineKeyboardButton("🔙 Menu", callback_data="menu_back"),
        ],
    ])


def _settings_keyboard() -> InlineKeyboardMarkup:
    copy_on = False
    try:
        from monitoring.telegram_wealth_manager import get_copy_trade_enabled
        copy_on = get_copy_trade_enabled()
    except Exception:
        pass
    copy_label = "🔁 Copy Wallet : ON ✅" if copy_on else "🔁 Copy Wallet : OFF ❌"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Thresholds", callback_data="settings_thresholds"),
            InlineKeyboardButton("💰 Capital", callback_data="settings_capital"),
        ],
        [
            InlineKeyboardButton("🔁 Simulation", callback_data="settings_toggle_sim"),
            InlineKeyboardButton("🤖 Auto-Trade", callback_data="settings_autotrade"),
        ],
        [InlineKeyboardButton(copy_label, callback_data="settings_toggle_copy")],
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
            if isinstance(data, dict):
                return data.get("market_count", data.get("count", len(data.get("signals", []))))
            return len(data) if isinstance(data, list) else 0
    except Exception:
        pass
    return 0


async def _get_balance() -> float:
    """Balance USDC du portefeuille Polymarket."""
    relayer_addr = os.getenv("RELAYER_API_KEY_ADDRESS")
    if not relayer_addr:
        return _get_capital()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            r = await client.get(f"https://data-api.polymarket.com/value?user={relayer_addr}")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    return float(data[0].get("value", 0))
                if isinstance(data, dict):
                    return float(data.get("value", 0))
    except Exception:
        pass
    return _get_capital()


async def _get_start_text() -> str:
    sim = os.getenv("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")
    mode = "LIVE" if not sim else "SIM"
    n = _get_market_count()
    balance = await _get_balance()
    return (
        f"⚡ <b>NEXUS CAPITAL</b>\n"
        f"<i>Prediction Market Intelligence</i>\n"
        f"{LINE}\n"
        f"● {mode}  📡 {n} marchés  💰 ${balance:,.2f}\n"
        f"{LINE}"
    )


async def _get_scan_text() -> str:
    try:
        from config.settings import settings
        from paperclip_bridge import get_pending_signals

        threshold = getattr(settings, "MIN_EDGE_THRESHOLD", 5.0) or 5.0
        last_scan_ts = 0
        try:
            for fname in ("defi_yield_state.json", "paperclip_pending_signals.json", "dashboard_state.json"):
                p = Path(__file__).resolve().parent.parent / fname
                if p.exists():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    ts = data.get("last_scan_ts") or data.get("last_updated")
                    if ts:
                        if isinstance(ts, (int, float)):
                            last_scan_ts = int(ts)
                        elif isinstance(ts, str):
                            try:
                                last_scan_ts = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
                            except Exception:
                                pass
                    break
        except Exception:
            pass
        mins = "—"
        if last_scan_ts:
            delta = int(datetime.now(timezone.utc).timestamp()) - last_scan_ts
            mins = f"{delta // 60}min ago" if delta >= 60 else "<1min ago"

        signals = get_pending_signals()
        n_assets = _get_market_count()
        n_signals = len(signals)

        header = (
            f"🔍 <b>MARKET SCANNER</b>\n"
            f"{LINE}\n"
            f"📡 Assets suivis   : {n_assets}\n"
            f"🟢 Signaux actifs  : {n_signals}\n"
            f"⚡ Min Edge requis : {threshold}%\n"
            f"🕐 Dernier scan    : {mins}\n"
            f"{LINE}\n"
        )
        if not signals:
            return (
                header
                + f"🔍 Scanner actif — {n_assets} marchés surveillés\n"
                + f"Aucun signal ≥{threshold}% pour l'instant\n"
                + f"Prochain scan dans 30s\n\n{LINE}"
            )

        lines = [header + "TOP SIGNALS :\n"]
        mt_map = {"binary": "BINARY", "multi_outcome": "MULTI", "scalar": "SCALAR"}
        for s in signals[:5]:
            q = (s.get("question") or str(s.get("market_id", "")))[:40]
            mt = mt_map.get(str(s.get("market_type", "binary")).lower(), "BINARY")
            rec = s.get("recommended_outcome") or s.get("side", "?")
            price = float(s.get("polymarket_price") or s.get("price") or 0.5)
            edge = float(s.get("edge_pct", 0))
            emoji = "⚡" if s.get("signal_strength") == "STRONG_BUY" else "🟢"
            lines.append(f"{emoji} [{mt}] {q}\n→ {rec} @ ${price:.2f} | edge: {edge:.1f}%")
        lines.append(f"\n{LINE}")
        return "\n".join(lines)
    except Exception as e:
        log.exception("Scan failed: %s", e)
        return f"🔍 <b>MARKET SCANNER</b>\n{LINE}\n❌ Erreur: {e}"


async def _get_portfolio_text() -> str:
    header = f"💼 <b>PORTFOLIO</b>\n{LINE}\n"
    try:
        balance = await _get_balance()
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
        return (
            f"{header}"
            f"💰 Balance      ${balance:,.2f} USDC\n"
            f"📈 P&amp;L Today    {pnl_sign}${pnl_today:,.2f} ({pnl_sign}{pnl_pct:.1f}%)\n"
            f"🎯 Positions    {len(positions)} ouvertes\n"
            f"✅ Win Rate     {win_rate:.0f}% ({wins} trades)\n"
            f"{LINE}"
        )
    except Exception as e:
        log.exception("Portfolio failed: %s", e)
        return f"{header}❌ Erreur: {e}"


async def _fetch_market_meta(market_id: str) -> tuple[str, int]:
    """Récupère question et jours jusqu'à résolution."""
    try:
        from config.settings import SETTINGS
        gamma_url = "https://gamma-api.polymarket.com"
        pm = SETTINGS.get("polymarket")
        if pm:
            gamma_url = getattr(pm, "gamma_url", gamma_url)
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            for url in (f"{gamma_url}/markets/{market_id}", f"{gamma_url}/markets?condition_id={market_id}"):
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                data = r.json()
                m = data[0] if isinstance(data, list) and data else data
                if not isinstance(m, dict):
                    continue
                q = (m.get("question") or m.get("groupItemTitle") or market_id[:45])[:45]
                end = m.get("endDate") or m.get("end_date_iso") or ""
                if end:
                    try:
                        from datetime import datetime as dt
                        end_str = str(end).replace("Z", "+00:00")
                        end_dt = dt.fromisoformat(end_str)
                        if end_dt.tzinfo is None:
                            end_dt = end_dt.replace(tzinfo=timezone.utc)
                        now = datetime.now(timezone.utc)
                        days = max(0, (end_dt - now).days)
                        return q, days
                    except Exception:
                        pass
                return q, 0
    except Exception:
        pass
    return (market_id or "")[:45], 0


async def _get_positions_detail(context: ContextTypes.DEFAULT_TYPE | None = None
                                ) -> tuple[str, InlineKeyboardMarkup, list[dict]]:
    """Retourne (texte, clavier, positions_list) pour le menu Positions."""
    try:
        from monitoring.trade_logger import trade_logger
        from data.polymarket_client import PolymarketClient
        positions = trade_logger.get_positions()
        if not positions:
            return f"📋 <b>POSITIONS OUVERTES</b>\n{LINE}\nAucune position ouverte.\n{LINE}", _positions_keyboard(), []

        lines = [f"📋 <b>POSITIONS OUVERTES</b>\n{LINE}\n"]
        pos_list: list[dict] = []
        pm = PolymarketClient()
        for p in positions[:10]:
            mid = p.get("market_id") or ""
            outcome = p.get("outcome") or "?"
            size = float(p.get("size") or 0)
            entry = float(p.get("avg_price") or 0)
            question, days = await _fetch_market_meta(mid)
            current_price = await pm.get_mid_price(mid, outcome) if mid else None
            current = (current_price * size) if current_price else (entry * size)
            pnl_pct = ((current - entry * size) / (entry * size) * 100) if entry > 0 and size > 0 else 0
            pnl_sign = "+" if pnl_pct >= 0 else ""
            q_show = f"{question}..." if len(question) >= 45 else question
            lines.append(
                f"🎯 {q_show}\n"
                f"Side: {outcome} | Entrée: ${entry * size:,.2f} | Size: ${size * entry:,.2f}\n"
                f"Valeur: ${current:,.2f} | P&amp;L: {pnl_sign}{pnl_pct:.1f}%\n"
                f"Résolution: dans {days}j"
            )
            pos_list.append({"market_id": mid, "outcome": outcome, "size": size, "avg_price": entry, "question": question})
        await pm.close()
        lines.append(f"\n{LINE}")
        kb = InlineKeyboardMarkup([
            *[[InlineKeyboardButton("🔴 Exit", callback_data=f"exit_req_{i}")] for i in range(len(pos_list))],
            [InlineKeyboardButton("🔙 Portfolio", callback_data="btn_portfolio")],
        ])
        if context:
            context.user_data["positions_list"] = pos_list
        return "\n".join(lines), kb, pos_list
    except Exception as e:
        log.exception("Positions failed: %s", e)
        return f"📋 <b>POSITIONS OUVERTES</b>\n{LINE}\n❌ {e}", _positions_keyboard(), []


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
    header = f"🤖 <b>AI AGENTS — SWARM NEXUS</b>\n{LINE}\n"
    try:
        p = Path(__file__).resolve().parent.parent / "ai_debates_log.json"
        if not p.exists():
            return (
                f"{header}"
                f"⏳ En veille\n"
                f"Activation automatique sur edge ≥15%\n"
                f"{LINE}"
            )
        data = json.loads(p.read_text(encoding="utf-8"))
        latest = data.get("latest_swarm", {})
        debates = data.get("debates", [])

        if not latest and not debates:
            return (
                f"{header}"
                f"⏳ En veille\n"
                f"Activation automatique sur edge ≥15%\n"
                f"{LINE}"
            )

        lines = [header]
        if debates:
            role_emoji = {"Quant Analyst": "📊", "Risk Manager": "⚠️", "Head Analyst": "🎯"}
            for d in debates[-3:]:
                role = str(d.get("role") or d.get("agent", "Agent"))[:20]
                verdict = str(d.get("message") or d.get("content", d.get("verdict", "—")))[:80]
                emoji = role_emoji.get(role, "💬")
                lines.append(f"{emoji} {role}   → {verdict}")
        else:
            for r in ["Quant Analyst", "Risk Manager", "Head Analyst"]:
                verdict = str(latest.get("verdict", "—"))[:60]
                lines.append(f"📊 {r}   → {verdict}")
        approved = latest.get("approved", False)
        consensus = "APPROVED ✅" if approved else "REJECTED ❌"
        lines.append(f"\nConsensus : {consensus}")
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


async def _get_whales_text() -> str:
    header = f"🐳 <b>WHALE TRACKER</b>\n{LINE}\n"
    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            r = await client.get("https://data-api.polymarket.com/trades", params={"size": 20})
            if r.status_code != 200:
                return f"{header}❌ API indisponible\n{LINE}"
            trades = r.json()
        if not isinstance(trades, list):
            return f"{header}Aucun trade récent.\n{LINE}"
        whales = []
        for t in trades:
            size = float(t.get("size") or 0)
            price = float(t.get("price") or 0)
            amount_usd = size * price
            if amount_usd >= 1000:
                whales.append({
                    "title": (t.get("title") or t.get("slug", "?"))[:45],
                    "side": t.get("side", "?"),
                    "outcome": t.get("outcome", "?"),
                    "amount": amount_usd,
                })
        whales = whales[:5]
        if not whales:
            return f"{header}Aucun trade &gt;$1000 récent.\n{LINE}"
        lines = [header]
        for w in whales:
            lines.append(f"▸ <b>${w['amount']:,.0f}</b> {w['side']} {w['outcome']}\n  <i>{w['title']}</i>")
        lines.append(f"\n{LINE}")
        return "\n".join(lines)
    except Exception as e:
        log.exception("Whales failed: %s", e)
        return f"{header}❌ {e}\n{LINE}"


async def _get_market_text(query: str) -> tuple[str, InlineKeyboardMarkup]:
    """Fiche Market Object pour /market <slug_ou_question>. Cache 60s, timeout 5s."""
    if not query or not query.strip():
        return (
            f"🎯 <b>MARKET INTELLIGENCE</b>\n{LINE}\n"
            f"Usage: /market &lt;slug ou question&gt;\n"
            f"Ex: /market trump-election\n"
            f"Ex: /market fed-decision-october\n{LINE}",
            _back_keyboard(),
        )
    query = query.strip()
    now = time.time()
    cache_key = f"market:{query}"
    if cache_key in _market_cache:
        data, ts = _market_cache[cache_key]
        if now - ts < CACHE_TTL:
            return _format_market_text(data)
    api_url = os.getenv("DASHBOARD_URL", "https://nexus-capital-eight.vercel.app").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            r = await client.get(f"{api_url}/api/market/{query}")
            if r.status_code != 200:
                r2 = await client.get(f"{api_url}/api/market/search", params={"q": query})
                if r2.status_code != 200:
                    return (
                        f"🎯 <b>MARKET INTELLIGENCE</b>\n{LINE}\n"
                        f"❌ Marché non trouvé: {query[:40]}\n{LINE}",
                        _back_keyboard(),
                    )
                m = r2.json()
            else:
                m = r.json()
    except Exception as e:
        log.exception("Market fetch: %s", e)
        return (
            f"🎯 <b>MARKET INTELLIGENCE</b>\n{LINE}\n"
            f"❌ Erreur API: {e}\n{LINE}",
            _back_keyboard(),
        )
    if not m or m.get("error"):
        return (
            f"🎯 <b>MARKET INTELLIGENCE</b>\n{LINE}\n"
            f"❌ Marché non trouvé\n{LINE}",
            _back_keyboard(),
        )
    _market_cache[cache_key] = (m, now)
    if len(_market_cache) > 50:
        oldest = min(_market_cache, key=lambda k: _market_cache[k][1])
        del _market_cache[oldest]
    return _format_market_text(m)


def _format_market_text(m: dict) -> tuple[str, InlineKeyboardMarkup]:
    yes_pct = int((m.get("yes_price") or 0.5) * 100)
    no_pct = int((m.get("no_price") or 0.5) * 100)
    vol = (m.get("volume_24h") or 0)
    whale = m.get("whale_activity") or {}
    smart = m.get("smart_money_signal", "neutral")
    smart_emoji = "🟢" if smart == "bullish" else "🔴" if smart == "bearish" else "⚪"
    edge = m.get("nexus_edge")
    score = m.get("nexus_score")
    edge_str = f"{edge:.1f}%" if edge is not None else "—"
    score_str = f"{score:.0f}/100" if score is not None else "—"
    poly_slug = m.get("slug") or ""
    cid = m.get("market_id", "")
    if poly_slug and not str(poly_slug).startswith("0x"):
        poly_url = f"https://polymarket.com/event/{poly_slug}"
    else:
        poly_url = f"https://polymarket.com/market/{cid}" if cid else "https://polymarket.com"
    text = (
        f"🎯 <b>MARKET INTELLIGENCE</b>\n"
        f"{LINE}\n"
        f"{(m.get('question') or '')[:80]}\n"
        f"YES: {yes_pct}% | NO: {no_pct}\n"
        f"Volume 24h: ${vol:,.0f}\n"
        f"Smart money: {smart_emoji} {smart.upper()} ({whale.get('large_trades_count', 0)} gros trades)\n"
        f"Edge Nexus: {edge_str} | Score: {score_str}\n"
        f"{LINE}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Voir sur Polymarket", url=poly_url)],
        [InlineKeyboardButton("🔙 Menu", callback_data="menu_back")],
    ])
    return text, kb


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

async def _ack_then_reply(update: Update, get_content, fallback: str, default_kb, parse_mode="HTML"):
    """Envoie ⏳ immédiatement, puis remplace par le contenu (<1s target). get_content peut retourner str ou (str, kb)."""
    try:
        ack = await update.message.reply_text("⏳", parse_mode=None)
    except Exception:
        ack = None
    try:
        result = await asyncio.wait_for(get_content(), timeout=10.0)
        content = result[0] if isinstance(result, tuple) else result
        reply_markup = result[1] if isinstance(result, tuple) and len(result) > 1 else default_kb
    except asyncio.TimeoutError:
        content = fallback
        reply_markup = default_kb
    except Exception as e:
        log.exception("Handler error: %s", e)
        content = f"{fallback}\n\n⚠️ {str(e)[:80]}"
        reply_markup = default_kb
    if ack:
        try:
            await ack.edit_text(content, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception:
            await update.message.reply_text(content, parse_mode=parse_mode, reply_markup=reply_markup)
    else:
        await update.message.reply_text(content, parse_mode=parse_mode, reply_markup=reply_markup)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset user state + clear pending callbacks on /start."""
    context.user_data.clear()
    text = await _get_start_text()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=_main_keyboard())


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack_then_reply(update, _get_portfolio_text, f"💼 <b>PORTFOLIO</b>\n{LINE}\nDonnées en cours...", _portfolio_keyboard())


def _scan_fallback() -> str:
    """Fallback when scan fails — never leave user with nothing."""
    n = _get_market_count()
    return (
        f"🔍 <b>SCANNER</b>\n{LINE}\n"
        f"🔍 Scanner actif — {n} marchés surveillés\n"
        f"Aucun signal ≥5% pour l'instant\n"
        f"Prochain scan dans 30s\n\n{LINE}"
    )


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack_then_reply(update, _get_scan_text, _scan_fallback(), _scan_keyboard())


async def cmd_agents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack_then_reply(update, _get_agents_text, f"🤖 <b>AI AGENTS</b>\n{LINE}\nDonnées en cours...", _back_keyboard())


async def cmd_whales(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack_then_reply(update, _get_whales_text, f"🐳 <b>WHALES</b>\n{LINE}\nDonnées en cours...", _back_keyboard())


async def cmd_referral(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"🤝 <b>REFERRAL</b>\n{LINE}\n<i>Programme de parrainage à venir.</i>\n{LINE}",
        parse_mode="HTML",
        reply_markup=_back_keyboard(),
    )


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = _get_settings_text()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=_settings_keyboard())


async def cmd_market(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fiche Market Object : /market <slug_ou_question> (cache 60s, timeout 5s)."""
    query = " ".join((context.args or [])).strip()
    try:
        text, kb = await asyncio.wait_for(_get_market_text(query), timeout=5.0)
    except asyncio.TimeoutError:
        text = f"🎯 <b>MARKET INTELLIGENCE</b>\n{LINE}\nDonnées en cours... Réessayez.\n{LINE}"
        kb = _back_keyboard()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def cmd_exit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche les positions ouvertes avec boutons [🔴 Exit]."""
    async def _get():
        t, k, _ = await _get_positions_detail(context)
        return (t, k)
    await _ack_then_reply(
        update,
        _get,
        f"📋 <b>POSITIONS</b>\n{LINE}\nDonnées en cours...",
        _positions_keyboard(),
    )


def _is_admin(chat_id: int) -> bool:
    """Vérifie si le chat_id est un admin (accès permanent)."""
    admin_ids = (
        os.getenv("ADMIN_TELEGRAM_CHAT_IDS", "")
        or os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
        or os.getenv("TELEGRAM_CHAT_ID", "")
    )
    if not admin_ids:
        return False
    for aid in str(admin_ids).replace(",", " ").split():
        try:
            if int(aid.strip()) == chat_id:
                return True
        except ValueError:
            pass
    return False


async def _upsert_user_token(telegram_chat_id: str) -> tuple[str, bool]:
    """
    Génère un token et upsert dans Supabase users.
    Returns (access_token, is_active).
    """
    token = uuid.uuid4().hex[:8].lower()
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        log.warning("Supabase non configuré pour /access")
        return token, False

    is_admin = _is_admin(int(telegram_chat_id))
    payload = {
        "telegram_chat_id": str(telegram_chat_id),
        "access_token": token,
        "is_active": is_admin,
        "expires_at": None if is_admin else None,
        "plan": "admin" if is_admin else "free",
    }

    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        try:
            r = await client.get(
                f"{url}/rest/v1/users",
                params={"telegram_chat_id": f"eq.{telegram_chat_id}", "select": "id"},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            if r.status_code == 200 and r.json():
                row = r.json()[0]
                rid = row.get("id")
                await client.patch(
                    f"{url}/rest/v1/users",
                    params={"id": f"eq.{rid}"},
                    headers=headers,
                    json={
                        "access_token": token,
                        "is_active": is_admin,
                        "expires_at": None,
                        "plan": "admin" if is_admin else "free",
                    },
                )
            else:
                await client.post(f"{url}/rest/v1/users", headers=headers, json=payload)
        except Exception as e:
            log.exception("Supabase upsert user: %s", e)
            return token, False
    return token, is_admin


async def cmd_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Génère un token dashboard et envoie le lien privé (timeout 5s)."""
    try:
        ack = await update.message.reply_text("⏳", parse_mode=None)
    except Exception:
        ack = None
    try:
        chat_id = str(update.effective_user.id if update.effective_user else update.effective_chat.id)
        token, is_active = await asyncio.wait_for(_upsert_user_token(chat_id), timeout=5.0)
    except asyncio.TimeoutError:
        token, is_active = "", False
    dashboard_url = os.getenv("DASHBOARD_URL", "https://nexus-capital-eight.vercel.app")
    link = f"{dashboard_url.rstrip('/')}?token={token}" if token else "—"

    if not is_active:
        text = (
            f"🔐 <b>ACCÈS DASHBOARD</b>\n{LINE}\n"
            f"Votre lien :\n<code>{link}</code>\n\n"
            f"⚠️ <b>Accès restreint</b>\n"
            f"Votre compte n'est pas encore actif.\n"
            f"S'abonnez pour débloquer le dashboard complet.\n{LINE}"
        )
    else:
        text = (
            f"🔐 <b>Votre dashboard privé</b>\n{LINE}\n"
            f"{link}\n\n"
            f"<i>Ce lien est personnel — ne le partagez pas.</i>\n{LINE}"
        )
    kb = _back_keyboard()
    if ack:
        try:
            await ack.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def handle_wallet_paste(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """PASTE & MONITOR : intercepte une adresse 0x collée par l'utilisateur."""
    text = (update.message.text or "").strip()
    m = POLYGON_ADDRESS_PATTERN.match(text)
    if not m:
        return
    addr = m.group(0)
    msg = (
        f"🐳 <b>WALLET DÉTECTÉ</b>\n"
        f"{LINE}\n"
        f"<code>{addr}</code>\n"
        f"{LINE}"
    )
    await update.message.reply_text(
        msg,
        parse_mode="HTML",
        reply_markup=_wallet_confirm_keyboard(addr),
    )


async def handle_settings_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if POLYGON_ADDRESS_PATTERN.match(text):
        return
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

    def _safe_get(get_fn, fallback: str, kb):
        async def _run():
            try:
                return await asyncio.wait_for(get_fn(), timeout=10.0)
            except asyncio.TimeoutError:
                return fallback
            except Exception as e:
                log.exception("Callback error: %s", e)
                return f"{fallback}\n\n⚠️ {str(e)[:60]}"
        return _run

    # ── Main menu ──
    if data == "menu_back":
        context.user_data.clear()
        text = await _get_start_text()
        await edit(text, _main_keyboard())
        return

    if data == "btn_scan":
        await edit(f"🔍 <b>SCANNING...</b>\n{LINE}", None)
        text = await _safe_get(_get_scan_text, _scan_fallback(), None)()
        await edit(text, _scan_keyboard())
        return

    if data == "btn_portfolio":
        await edit(f"💼 <b>LOADING...</b>\n{LINE}", None)
        text = await _safe_get(_get_portfolio_text, f"💼 <b>PORTFOLIO</b>\n{LINE}\nDonnées en cours...", None)()
        await edit(text, _portfolio_keyboard())
        return

    if data == "portfolio_positions":
        await edit(f"📋 <b>LOADING...</b>\n{LINE}", None)
        try:
            text, kb, _ = await asyncio.wait_for(_get_positions_detail(context), timeout=5.0)
        except (asyncio.TimeoutError, Exception):
            text = f"📋 <b>POSITIONS</b>\n{LINE}\nDonnées en cours..."
            kb = _positions_keyboard()
        await edit(text, kb)
        return

    if data == "portfolio_history":
        await edit(f"📜 <b>LOADING...</b>\n{LINE}", None)
        text = await _safe_get(_get_history_text, f"📜 <b>HISTORIQUE</b>\n{LINE}\nDonnées en cours...", None)()
        await edit(text, _portfolio_keyboard())
        return

    if data == "btn_agents":
        await edit(f"🤖 <b>LOADING...</b>\n{LINE}", None)
        text = await _safe_get(_get_agents_text, f"🤖 <b>AI AGENTS</b>\n{LINE}\nDonnées en cours...", None)()
        await edit(text, _back_keyboard())
        return

    if data == "btn_btc":
        await edit(f"📈 <b>LOADING...</b>\n{LINE}", None)
        text = await _safe_get(_get_btc_text, f"📈 <b>BTC</b>\n{LINE}\nDonnées en cours...", None)()
        await edit(text, _back_keyboard())
        return

    if data == "btn_whales":
        await edit(f"🐳 <b>LOADING...</b>\n{LINE}", None)
        text = await _safe_get(_get_whales_text, f"🐳 <b>WHALES</b>\n{LINE}\nDonnées en cours...", None)()
        await edit(text, _back_keyboard())
        return

    if data == "btn_referral":
        await edit(f"🤝 <b>REFERRAL</b>\n{LINE}\n<i>Programme de parrainage à venir.</i>\n{LINE}", _back_keyboard())
        return

    # ── Paste & Monitor (wallet add/cancel) ──
    if data == "wallet_cancel":
        await edit("Annulé.")
        return

    if data.startswith("wallet_add_"):
        addr = data.replace("wallet_add_", "")
        if POLYGON_ADDRESS_PATTERN.match(addr):
            try:
                from monitoring.telegram_wealth_manager import add_whale_wallet
                if add_whale_wallet(addr):
                    await edit("✅ Wallet ajouté au whale tracker")
                else:
                    await edit("❌ Erreur lors de l'ajout.")
            except Exception as e:
                log.exception("wallet_add: %s", e)
                await edit(f"❌ Erreur: {e}")
        else:
            await edit("❌ Adresse invalide.")
        return

    # ── Exit position (confirmation) ──
    if data == "exit_cancel":
        await edit(f"📋 <b>LOADING...</b>\n{LINE}", None)
        text, kb, _ = await _get_positions_detail(context)
        await edit(text, kb)
        return

    if data.startswith("exit_req_"):
        idx_s = data.replace("exit_req_", "")
        try:
            idx = int(idx_s)
        except ValueError:
            return
        pos_list = context.user_data.get("positions_list") or []
        if idx < 0 or idx >= len(pos_list):
            return
        pos = pos_list[idx]
        question = (pos.get("question") or pos.get("market_id") or "?")[:30]
        await edit(
            f"Confirmer l'exit de <i>{question}</i> ?",
            _exit_confirm_keyboard(),
        )
        context.user_data["exit_pending"] = pos
        return

    if data == "exit_confirm":
        pos = context.user_data.pop("exit_pending", None)
        if not pos:
            await edit(f"⏱ Position expirée\n{LINE}", _main_keyboard())
            return
        await edit(f"⏳ Vente en cours...\n{LINE}", None)
        try:
            from execution.order_manager import OrderManager, OrderConfig
            om = OrderManager()
            try:
                size = float(pos.get("size") or 0)
                price = float(pos.get("avg_price") or 0.5)
                if size <= 0:
                    raise ValueError("Size invalide")
                current_price = await om.client.get_mid_price(pos["market_id"], pos["outcome"])
                sell_price = (current_price or price) * 0.98
                cfg = OrderConfig(
                    market_id=pos["market_id"],
                    outcome=pos["outcome"],
                    side="SELL",
                    size_usd=size * sell_price,
                    limit_price=sell_price,
                )
                order_id = await om.place_limit_order(cfg)
                from monitoring.trade_logger import trade_logger
                trade_logger.update_position(pos["market_id"], pos["outcome"], 0, 0)
                from monitoring.telegram_alerts import send_telegram_message
                mkt = (pos.get("question") or pos["market_id"])[:50]
                await send_telegram_message(f"🔴 EXIT — {mkt} soldé\nOrderID: {order_id}")
            finally:
                await om.client.close()
        except Exception as e:
            log.exception("Exit failed: %s", e)
            await edit(f"❌ Exit échoué: {e}\n{LINE}", _main_keyboard())
            return
        await edit(f"🔴 <b>EXIT EXÉCUTÉ</b>\n{LINE}\nPosition soldée.", _main_keyboard())
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

    if data == "settings_toggle_copy":
        try:
            from monitoring.telegram_wealth_manager import get_copy_trade_enabled, set_copy_trade_enabled
            cur = get_copy_trade_enabled()
            set_copy_trade_enabled(not cur)
        except Exception:
            pass
        await edit(_get_settings_text(), _settings_keyboard())
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
    """Delete webhook + clear pending updates. Prevents 409 when switching to polling."""
    import httpx
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
                r = await client.get(
                    f"https://api.telegram.org/bot{token}/deleteWebhook",
                    params={"drop_pending_updates": True},
                )
                if r.status_code != 200:
                    log.warning("deleteWebhook returned %s: %s", r.status_code, r.text[:200])
                await client.post(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    json={"offset": -1, "timeout": 0},
                )
            log.info("Telegram session cleared (webhook deleted, queue purged)")
            return True
        except Exception as e:
            log.warning("close_telegram_session attempt %d failed: %s", attempt + 1, e)
            if attempt < 2:
                await asyncio.sleep(2)
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
    """Single polling instance. Clears webhook/pending updates to avoid 409 Conflict."""
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
                ok = await close_telegram_session(token)
                if not ok:
                    log.warning("Session clear failed, continuing anyway…")
                await asyncio.sleep(3)

                app = Application.builder().token(token).build()
                app.add_handler(CommandHandler("start", cmd_start))
                app.add_handler(CommandHandler("portfolio", cmd_portfolio))
                app.add_handler(CommandHandler("scan", cmd_scan))
                app.add_handler(CommandHandler("market", cmd_market))
                app.add_handler(CommandHandler("agents", cmd_agents))
                app.add_handler(CommandHandler("whales", cmd_whales))
                app.add_handler(CommandHandler("referral", cmd_referral))
                app.add_handler(CommandHandler("settings", cmd_settings))
                app.add_handler(CommandHandler("exit", cmd_exit))
                app.add_handler(CommandHandler("access", cmd_access))
                app.add_handler(CallbackQueryHandler(callback_handler))
                app.add_handler(
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND & filters.Regex(POLYGON_ADDRESS_PATTERN),
                        handle_wallet_paste,
                    ),
                )
                app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings_text))

                await app.initialize()
                await app.start()
                await app.bot.set_my_commands([
                    BotCommand("start", "⚡ Menu principal"),
                    BotCommand("access", "🔐 Lien dashboard privé"),
                    BotCommand("portfolio", "💼 Solde et positions ouvertes"),
                    BotCommand("scan", "🔍 Derniers signaux détectés"),
                    BotCommand("market", "🎯 Fiche Market Object par slug/question"),
                    BotCommand("agents", "🤖 Débats IA en cours"),
                    BotCommand("whales", "🐳 Tracker les baleines"),
                    BotCommand("referral", "🤝 Mon lien d'affiliation"),
                    BotCommand("settings", "⚙️ Configurer le bot"),
                    BotCommand("exit", "🔴 Sortir d'une position"),
                ])
                poll_task = asyncio.create_task(app.updater.start_polling(drop_pending_updates=True))

                log.info("Telegram poller démarré — seule instance active (drop_pending_updates=True)")
                delay = base_delay

                while poll_task and not poll_task.done():
                    await asyncio.sleep(10)

                if poll_task and poll_task.done():
                    exc = poll_task.exception()
                    if exc is not None:
                        raise exc
                    log.warning("Telegram poller s'est arrêté sans exception (restart)")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if _is_conflict_error(e):
                    log.error("Telegram 409 Conflict — autre instance ou webhook actif. Purge + retry 5s: %s", e)
                    await close_telegram_session(token)
                    await asyncio.sleep(5)
                    delay = base_delay
                else:
                    log.exception("Telegram poller erreur (retry dans %.0fs): %s", delay, e)
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
                    except Exception as cleanup_err:
                        log.debug("Telegram cleanup: %s", cleanup_err)
    except asyncio.CancelledError:
        log.info("Telegram poller arrêté")
        raise
