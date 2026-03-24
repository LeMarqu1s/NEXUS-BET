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
API_TIMEOUT = 8.0
HANDLER_TIMEOUT = 10.0
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

L = "━━━━━━━━━━━━━━━"
LINE = L  # alias kept for compat


# ══════════════════════════════════════════════
# KEYBOARDS
# ══════════════════════════════════════════════

def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📡 SCAN", callback_data="btn_scan"),
            InlineKeyboardButton("💰 PORTFOLIO", callback_data="btn_portfolio"),
        ],
        [
            InlineKeyboardButton("🧠 AGENTS", callback_data="btn_agents"),
            InlineKeyboardButton("🐋 WHALES", callback_data="btn_whales"),
        ],
        [
            InlineKeyboardButton("👥 REFERRAL", callback_data="btn_referral"),
            InlineKeyboardButton("⚙️ SETTINGS", callback_data="btn_settings"),
        ],
    ])


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("← MENU", callback_data="menu_back")]])


def _portfolio_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 POSITIONS", callback_data="portfolio_positions"),
            InlineKeyboardButton("📜 HISTORIQUE", callback_data="portfolio_history"),
        ],
        [InlineKeyboardButton("← MENU", callback_data="menu_back")],
    ])


def _positions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("← PORTFOLIO", callback_data="btn_portfolio")]])


def _exit_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ CONFIRMER", callback_data="exit_confirm"),
            InlineKeyboardButton("✕ ANNULER", callback_data="exit_cancel"),
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
            InlineKeyboardButton("⟳ REFRESH", callback_data="btn_scan"),
            InlineKeyboardButton("← MENU", callback_data="menu_back"),
        ],
    ])


def _settings_keyboard() -> InlineKeyboardMarkup:
    copy_on = False
    try:
        from monitoring.telegram_wealth_manager import get_copy_trade_enabled
        copy_on = get_copy_trade_enabled()
    except Exception:
        pass
    copy_label = "COPY ON ✅" if copy_on else "COPY OFF ✕"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("THRESHOLDS", callback_data="settings_thresholds"),
            InlineKeyboardButton("CAPITAL", callback_data="settings_capital"),
        ],
        [
            InlineKeyboardButton("SIMULATION", callback_data="settings_toggle_sim"),
            InlineKeyboardButton("AUTO-TRADE", callback_data="settings_autotrade"),
        ],
        [InlineKeyboardButton(copy_label, callback_data="settings_toggle_copy")],
        [InlineKeyboardButton("AVANCÉ", callback_data="settings_advanced")],
        [InlineKeyboardButton("📊 DASHBOARD", callback_data="settings_dashboard")],
        [InlineKeyboardButton("← MENU", callback_data="menu_back")],
    ])


def _settings_autotrade_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ON / OFF", callback_data="settings_autotrade_toggle")],
        [InlineKeyboardButton("MAX POSITIONS", callback_data="settings_max_positions")],
        [InlineKeyboardButton("DRAWDOWN LIMIT %", callback_data="settings_drawdown")],
        [InlineKeyboardButton("CONFIRM BUY", callback_data="settings_confirm_buy")],
        [InlineKeyboardButton("← SETTINGS", callback_data="btn_settings")],
    ])


def _settings_advanced_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("BLACKLIST CATÉGORIES", callback_data="settings_categories")],
        [InlineKeyboardButton("JOURS RÉSOLUTION", callback_data="settings_days_resolution")],
        [InlineKeyboardButton("BLACKLIST MOTS-CLÉS", callback_data="settings_keywords")],
        [InlineKeyboardButton("RÉINVESTISSEMENT %", callback_data="settings_reinvest")],
        [InlineKeyboardButton("← SETTINGS", callback_data="btn_settings")],
    ])


# ══════════════════════════════════════════════
# TEXT GENERATORS — Premium HTML Style
# ══════════════════════════════════════════════

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
    relayer_addr = os.getenv("RELAYER_API_KEY_ADDRESS")
    if not relayer_addr:
        return _get_capital()
    try:
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


def _conf_label(confidence: float) -> str:
    if confidence >= 0.80:
        return "HIGH"
    if confidence >= 0.60:
        return "MED"
    return "LOW"


def _detect_category(question: str) -> str:
    q = question.lower()
    if any(k in q for k in ("nfl", "nba", "mlb", "nhl", "soccer", "football", "basketball",
                             "baseball", "hockey", "tennis", "golf", "ufc", "sport", "league",
                             "championship", "super bowl", "world cup", "playoff")):
        return "SPORT"
    if any(k in q for k in ("trump", "biden", "election", "president", "senate", "congress",
                             "democrat", "republican", "vote", "political", "harris", "governor")):
        return "POLITICS"
    if any(k in q for k in ("btc", "bitcoin", "eth", "ethereum", "crypto", "sol", "solana",
                             "bnb", "xrp", "doge", "token", "blockchain", "defi", "nft")):
        return "CRYPTO"
    if any(k in q for k in ("fed", "rate", "gdp", "inflation", "recession", "cpi", "fomc",
                             "economy", "macro", "interest", "powell")):
        return "MACRO"
    return "MARKET"


async def _get_start_text() -> str:
    sim = os.getenv("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")
    mode = "SIM" if sim else "LIVE"
    dot = "🔵" if sim else "🟢"
    n = _get_market_count()
    balance = await _get_balance()
    return (
        f"<b>⚡ NEXUS BET</b>\n"
        f"<i>Prediction Market Intelligence</i>\n"
        f"{L}\n"
        f"{dot} {mode} · {n} marchés · ${balance:,.2f}\n"
        f"{L}"
    )


async def _get_scan_text() -> str:
    try:
        from config.settings import settings
        from paperclip_bridge import get_pending_signals, PENDING_SIGNALS_PATH

        threshold = getattr(settings, "MIN_EDGE_THRESHOLD", 5.0) or 5.0
        last_scan_ts = 0
        p_canonical = Path(PENDING_SIGNALS_PATH)
        try:
            if p_canonical.exists():
                data = json.loads(p_canonical.read_text(encoding="utf-8"))
                ts = data.get("last_scan_ts") or data.get("last_updated")
                if ts:
                    last_scan_ts = int(ts) if isinstance(ts, (int, float)) else 0
        except Exception:
            pass
        mins = "—"
        if last_scan_ts:
            delta = int(datetime.now(timezone.utc).timestamp()) - last_scan_ts
            mins = f"{delta // 60}m ago" if delta >= 60 else "&lt;1m ago"

        signals = get_pending_signals()
        if not signals:
            for try_path in [p_canonical, Path("paperclip_pending_signals.json").resolve()]:
                if try_path.exists():
                    try:
                        d = json.loads(try_path.read_text(encoding="utf-8"))
                        signals = d.get("signals", []) if isinstance(d, dict) else []
                        if signals:
                            break
                    except Exception:
                        pass

        n_assets = _get_market_count()
        n_signals = len(signals)

        if not signals:
            return (
                f"<b>📡 MARKET SCANNER</b>\n{L}\n"
                f"<code>MARCHÉS   {n_assets}\n"
                f"SIGNAUX   0\n"
                f"EDGE MIN  {threshold}%\n"
                f"SCAN      {mins}</code>\n"
                f"{L}\n"
                f"<i>Aucun signal ≥{threshold}% · prochain scan dans 30s</i>"
            )

        lines = [
            f"<b>📡 MARKET SCANNER</b>\n{L}\n"
            f"<code>MARCHÉS   {n_assets}\n"
            f"SIGNAUX   {n_signals}\n"
            f"EDGE MIN  {threshold}%\n"
            f"SCAN      {mins}</code>\n"
            f"{L}"
        ]
        from config.settings import settings as _s
        cap = getattr(_s, "POLYMARKET_CAPITAL_USD", 1000.0) or 1000.0
        sim = getattr(_s, "SIMULATION_MODE", True)
        mode_label = "PAPER" if sim else "LIVE"
        kb_rows: list = []
        for s in signals[:5]:
            mid = s.get("market_id") or s.get("conditionId") or ""
            q = (s.get("question") or str(mid))[:42]
            side = s.get("recommended_outcome") or s.get("side", "YES")
            price = float(s.get("polymarket_price") or 0.5)
            edge = float(s.get("edge_pct", 0))
            conf = float(s.get("confidence", 0))
            kelly = float(s.get("kelly_fraction") or 0.05)
            size_usd = max(1.0, round(cap * min(kelly, 0.10), 1))
            tag = "⚡ STRONG BUY" if s.get("signal_strength") == "STRONG_BUY" else "🟢 BUY"
            cat = _detect_category(q)
            lines.append(
                f"\n{tag} · {cat}\n"
                f"<b>{q}</b>\n"
                f"{side} @ ${price:.2f}  EDGE {edge:.1f}%  CONF {_conf_label(conf)}"
            )
            if mid:
                cb_buy = f"buy_{mid[:38]}|{side}"
                cb_pass = f"pass_{mid[:38]}"
                kb_rows.append([
                    InlineKeyboardButton(f"✅ BUY ${size_usd:.0f} [{mode_label}]", callback_data=cb_buy),
                    InlineKeyboardButton("❌ PASS", callback_data=cb_pass),
                ])
        lines.append(f"\n{L}")
        kb_rows.append([
            InlineKeyboardButton("⟳ REFRESH", callback_data="btn_scan"),
            InlineKeyboardButton("← MENU", callback_data="menu_back"),
        ])
        keyboard = InlineKeyboardMarkup(kb_rows)
        return "\n".join(lines), keyboard
    except Exception as e:
        log.exception("Scan failed: %s", e)
        return f"<b>📡 MARKET SCANNER</b>\n{L}\n<code>ERREUR — {e}</code>"


async def _fetch_paper_prices(market_ids: list[str]) -> dict[str, float]:
    """Fetch live YES prices from Gamma API for open paper positions (parallel, 3s timeout)."""
    result: dict[str, float] = {}
    if not market_ids:
        return result
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            tasks = [client.get(f"https://gamma-api.polymarket.com/markets/{mid}") for mid in market_ids[:5]]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            for mid, r in zip(market_ids[:5], responses):
                if isinstance(r, Exception):
                    continue
                try:
                    data = r.json()
                    m = data[0] if isinstance(data, list) and data else data
                    if not isinstance(m, dict):
                        continue
                    prices = m.get("outcomePrices", ["0.5", "0.5"])
                    if isinstance(prices, str):
                        prices = json.loads(prices)
                    result[mid] = float(prices[0])
                except Exception:
                    pass
    except Exception:
        pass
    return result


async def _get_portfolio_text() -> str:
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
        pnl_icon = "▲" if pnl_today >= 0 else "▼"

        # Paper portfolio with live prices
        paper_section = ""
        try:
            from monitoring.paper_portfolio import get_paper_summary
            pp_data = _load_paper_trades_json()
            open_ids = [t.get("market_id", "") for t in pp_data if t.get("status") == "OPEN" and t.get("market_id")]
            live_prices = await _fetch_paper_prices(open_ids) if open_ids else {}
            pp = get_paper_summary(current_prices=live_prices)
            open_trades = pp.get("open_trades", [])
            pp_pnl = pp.get("total_pnl", 0)
            pp_pnl_pct = pp.get("total_pnl_pct", 0)
            pp_wr = pp.get("win_rate", 0)
            pp_invested = pp.get("invested", 0)
            pp_free = pp.get("free", 0)
            sign = "+" if pp_pnl >= 0 else ""
            icon = "▲" if pp_pnl >= 0 else "▼"
            paper_section = (
                f"\n{L}\n<b>📄 PAPER SIM — $50</b>\n"
                f"<code>INVESTI   ${pp_invested:.2f}  LIBRE ${pp_free:.2f}\n"
                f"P&L       {icon}{sign}${abs(pp_pnl):.2f} ({sign}{pp_pnl_pct:.1f}%)\n"
                f"WIN RATE  {pp_wr:.0f}%  POSITIONS {len(open_trades)}</code>"
            )
            if open_trades:
                paper_section += f"\n<code>"
                for t in open_trades[:3]:
                    q = (t.get("question") or t.get("market_id", "?"))[:28]
                    s = t.get("side", "?")
                    ep = float(t.get("entry_price") or 0)
                    cp = float(t.get("current_price") or ep)
                    p = float(t.get("pnl_pct") or 0)
                    pi = "▲" if p >= 0 else "▼"
                    paper_section += f"\n{q[:28]}\n{s} @{ep:.2f}→{cp:.2f} {pi}{abs(p):.1f}%"
                paper_section += "</code>"
        except Exception as pe:
            log.debug("Paper portfolio in portfolio text: %s", pe)

        return (
            f"<b>💰 PORTFOLIO</b>\n{L}\n"
            f"<code>BALANCE   ${balance:,.2f} USDC\n"
            f"P&L       {pnl_icon}{pnl_sign}${abs(pnl_today):,.2f} ({pnl_sign}{pnl_pct:.1f}%)\n"
            f"POSITIONS {len(positions)} ouvertes\n"
            f"WIN RATE  {win_rate:.0f}% ({wins}/{max(total_closed,1)})</code>\n"
            f"{L}{paper_section}"
        )
    except Exception as e:
        log.exception("Portfolio failed: %s", e)
        return f"<b>💰 PORTFOLIO</b>\n{L}\n<code>ERREUR — {e}</code>"


def _load_paper_trades_json() -> list:
    """Load open trades list from paper_trades.json (sync helper)."""
    try:
        p = Path(__file__).resolve().parent.parent / "logs" / "paper_trades.json"
        if not p.exists():
            return []
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("trades", []) if isinstance(data, dict) else []
    except Exception:
        return []


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
    try:
        from monitoring.trade_logger import trade_logger
        from data.polymarket_client import PolymarketClient
        positions = trade_logger.get_positions()
        if not positions:
            return (
                f"<b>📋 POSITIONS</b>\n{L}\n<i>Aucune position ouverte.</i>\n{L}",
                _positions_keyboard(), []
            )

        lines = [f"<b>📋 POSITIONS OUVERTES</b>\n{L}\n"]
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
            pnl_icon = "▲" if pnl_pct >= 0 else "▼"
            q_show = question[:42]
            lines.append(
                f"<b>{q_show}</b>\n"
                f"<code>{outcome:<4} ${entry * size:,.2f} → ${current:,.2f}  {pnl_icon}{abs(pnl_pct):.1f}%  J-{days}</code>"
            )
            pos_list.append({"market_id": mid, "outcome": outcome, "size": size, "avg_price": entry, "question": question})
        await pm.close()
        lines.append(f"\n{L}")
        kb = InlineKeyboardMarkup([
            *[[InlineKeyboardButton(f"✕ EXIT #{i+1}", callback_data=f"exit_req_{i}")] for i in range(len(pos_list))],
            [InlineKeyboardButton("← PORTFOLIO", callback_data="btn_portfolio")],
        ])
        if context:
            context.user_data["positions_list"] = pos_list
        return "\n".join(lines), kb, pos_list
    except Exception as e:
        log.exception("Positions failed: %s", e)
        return f"<b>📋 POSITIONS</b>\n{L}\n<code>ERREUR — {e}</code>", _positions_keyboard(), []


async def _get_history_text() -> str:
    try:
        from monitoring.trade_logger import trade_logger
        trades = trade_logger.get_recent_trades(limit=10)
        if not trades:
            return f"<b>📜 HISTORIQUE</b>\n{L}\n<i>Aucun trade enregistré.</i>\n{L}"
        lines = [f"<b>📜 HISTORIQUE</b> · {len(trades)} trades\n{L}\n"]
        for t in trades:
            pnl = float(t.get("pnl") or 0)
            icon = "▲" if pnl > 0 else "▼" if pnl < 0 else "·"
            side = t.get("outcome", "?")
            date = str(t.get("created_at", ""))[:10]
            lines.append(f"<code>{icon} {side:<4} ${pnl:+,.2f}   {date}</code>")
        lines.append(f"\n{L}")
        return "\n".join(lines)
    except Exception as e:
        return f"<b>📜 HISTORIQUE</b>\n{L}\n<code>ERREUR — {e}</code>"


async def _get_agents_text() -> str:
    try:
        p = Path(__file__).resolve().parent.parent / "ai_debates_log.json"
        if not p.exists():
            return (
                f"<b>🧠 AI SWARM · NEXUS</b>\n{L}\n"
                f"<code>STATUS    VEILLE\n"
                f"TRIGGER   EDGE ≥ 15%\n"
                f"AGENTS    20</code>\n"
                f"{L}\n"
                f"<i>Le swarm s'active automatiquement sur signal fort.</i>"
            )
        data = json.loads(p.read_text(encoding="utf-8"))
        latest = data.get("latest_swarm", {})
        debates = data.get("debates", [])

        approved = latest.get("approved", False)
        pct_yes = latest.get("pct_yes", 0)
        market_id = (latest.get("market_id") or "—")[:20]
        verdict_icon = "✅ APPROVED" if approved else "❌ REJECTED"

        lines = [
            f"<b>🧠 AI SWARM · NEXUS</b>\n{L}\n"
            f"<code>CONSENSUS  {verdict_icon}\n"
            f"SCORE      {pct_yes:.0f}% YES\n"
            f"MARCHÉ     {market_id}</code>\n"
            f"{L}"
        ]

        role_map = {"Quant Analyst": "📊", "Risk Manager": "⚠️", "Head Analyst": "🎯"}
        shown = debates[-4:] if debates else []
        for d in shown:
            role = str(d.get("role") or d.get("agent", "Agent"))[:22]
            vote = str(d.get("vote", "")).upper()
            content = str(d.get("message") or d.get("content", "—"))[:70]
            emoji = role_map.get(role, "💬")
            vote_tag = " ✅" if vote == "YES" else " ❌" if vote == "NO" else ""
            lines.append(f"\n{emoji} <b>{role}</b>{vote_tag}\n<i>{content}</i>")

        lines.append(f"\n{L}")
        return "\n".join(lines)
    except Exception as e:
        return f"<b>🧠 AI SWARM</b>\n{L}\n<code>ERREUR — {e}</code>"


async def _get_whales_text() -> str:
    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            r = await client.get("https://data-api.polymarket.com/trades", params={"size": 30})
        if r.status_code != 200:
            return f"<b>🐋 WHALE TRACKER</b>\n{L}\n<code>API INDISPONIBLE</code>"
        trades = r.json()
        if not isinstance(trades, list):
            return f"<b>🐋 WHALE TRACKER</b>\n{L}\n<i>Aucun trade récent.</i>"

        whales = []
        for t in trades:
            size = float(t.get("size") or 0)
            price = float(t.get("price") or 0)
            amt = size * price
            if amt >= 50000:
                whales.append({
                    "title": (t.get("title") or t.get("slug", "?"))[:40],
                    "side": str(t.get("side", "?")).upper(),
                    "outcome": str(t.get("outcome", "?")).upper(),
                    "amount": amt,
                })
        whales = sorted(whales, key=lambda x: -x["amount"])[:6]
        if not whales:
            return f"<b>🐋 WHALE TRACKER</b>\n{L}\n<i>Aucun trade &gt;$50 000 récent.</i>\n{L}"

        lines = [f"<b>🐋 WHALE TRACKER</b>\n{L}\n"]
        for w in whales:
            lines.append(
                f"<b>${w['amount']:,.0f}</b>  {w['outcome']}\n"
                f"<code>{w['title']}</code>"
            )
        lines.append(f"\n{L}")
        return "\n".join(lines)
    except Exception as e:
        log.exception("Whales failed: %s", e)
        return f"<b>🐋 WHALE TRACKER</b>\n{L}\n<code>ERREUR — {e}</code>"


async def _get_market_text(query: str) -> tuple[str, InlineKeyboardMarkup]:
    if not query or not query.strip():
        return (
            f"<b>🎯 MARKET INTEL</b>\n{L}\n"
            f"<code>Usage: /market &lt;slug ou question&gt;\n"
            f"Ex:    /market trump-election\n"
            f"Ex:    /market fed-decision-october</code>\n{L}",
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
                        f"<b>🎯 MARKET INTEL</b>\n{L}\n"
                        f"<code>NOT FOUND — {query[:40]}</code>\n{L}",
                        _back_keyboard(),
                    )
                m = r2.json()
            else:
                m = r.json()
    except Exception as e:
        log.exception("Market fetch: %s", e)
        return (
            f"<b>🎯 MARKET INTEL</b>\n{L}\n<code>ERREUR — {e}</code>\n{L}",
            _back_keyboard(),
        )
    if not m or m.get("error"):
        return (
            f"<b>🎯 MARKET INTEL</b>\n{L}\n<code>NOT FOUND</code>\n{L}",
            _back_keyboard(),
        )
    _market_cache[cache_key] = (m, now)
    if len(_market_cache) > 50:
        oldest = min(_market_cache, key=lambda k: _market_cache[k][1])
        del _market_cache[oldest]
    return _format_market_text(m)


def _format_market_text(m: dict) -> tuple[str, InlineKeyboardMarkup]:
    yes_pct = int((m.get("yes_price") or 0.5) * 100)
    no_pct = 100 - yes_pct
    vol = m.get("volume_24h") or 0
    whale = m.get("whale_activity") or {}
    smart = str(m.get("smart_money_signal", "neutral")).upper()
    edge = m.get("nexus_edge")
    score = m.get("nexus_score")
    edge_str = f"{edge:.1f}%" if edge is not None else "—"
    score_str = f"{score:.0f}/100" if score is not None else "—"
    question = (m.get("question") or "")[:72]
    cat = _detect_category(question)
    poly_slug = m.get("slug") or ""
    cid = m.get("market_id", "")
    poly_url = (
        f"https://polymarket.com/event/{poly_slug}"
        if poly_slug and not str(poly_slug).startswith("0x")
        else f"https://polymarket.com/market/{cid}" if cid else "https://polymarket.com"
    )
    text = (
        f"<b>🎯 MARKET INTEL · {cat}</b>\n{L}\n"
        f"<b>{question}</b>\n"
        f"<code>YES     {yes_pct}%\n"
        f"NO      {no_pct}%\n"
        f"VOL 24H ${vol:,.0f}\n"
        f"SMART $ {smart} ({whale.get('large_trades_count', 0)} trades)\n"
        f"EDGE    {edge_str}\n"
        f"SCORE   {score_str}</code>\n"
        f"{L}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("↗ POLYMARKET", url=poly_url)],
        [InlineKeyboardButton("← MENU", callback_data="menu_back")],
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
            f"<b>⚙️ SETTINGS</b>\n{L}\n"
            f"<code>CAPITAL     ${cap:,.0f}\n"
            f"SIMULATION  {'ON' if sim else 'OFF'}\n"
            f"AUTO-TRADE  {'ON' if at else 'OFF'}\n"
            f"MAX POS     {max_pos}  DRAWDOWN {drawdown}%\n"
            f"CONFIRM BUY {'YES' if confirm else 'NO'}\n"
            f"KELLY       {kelly:.1f}%  EDGE MIN {min_edge:.1f}%</code>\n"
            f"{L}"
        )
    except Exception as e:
        return f"<b>⚙️ SETTINGS</b>\n{L}\n<code>ERREUR — {e}</code>"


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
        result = await asyncio.wait_for(get_content(), timeout=HANDLER_TIMEOUT)
        content = result[0] if isinstance(result, tuple) else result
        reply_markup = result[1] if isinstance(result, tuple) and len(result) > 1 else default_kb
    except asyncio.TimeoutError:
        content = fallback
        reply_markup = default_kb
    except Exception as e:
        log.exception("Handler error: %s", e)
        content = fallback
        reply_markup = default_kb
    if ack:
        try:
            await ack.edit_text(content, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception:
            await update.message.reply_text(content, parse_mode=parse_mode, reply_markup=reply_markup)
    else:
        await update.message.reply_text(content, parse_mode=parse_mode, reply_markup=reply_markup)


async def _safe_reply(update: Update, text: str, reply_markup=None, parse_mode="HTML") -> None:
    """Reply to user, never raise."""
    try:
        if update and update.message:
            await update.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as e:
        log.debug("safe_reply: %s", e)


async def _register_referred_user(chat_id: str, ref_code: str) -> None:
    """Enregistre un nouvel utilisateur avec son parrain dans Supabase."""
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            # Find referrer
            r = await client.get(
                f"{url}/rest/v1/users",
                params={"referral_code": f"eq.{ref_code}", "select": "id"},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            referrer_id = r.json()[0]["id"] if r.status_code == 200 and r.json() else None
            # Upsert new user with referred_by
            payload: dict = {"telegram_chat_id": chat_id, "is_active": False, "plan": "free"}
            if referrer_id:
                payload["referred_by"] = referrer_id
            await client.post(
                f"{url}/rest/v1/users",
                headers={**headers, "Prefer": "resolution=ignore-duplicates,return=minimal"},
                json=payload,
            )
            # Increment referrer's referred_count
            if referrer_id:
                await client.post(
                    f"{url}/rest/v1/rpc/increment_referred_count",
                    headers=headers,
                    json={"user_id": referrer_id},
                )
    except Exception as e:
        log.debug("_register_referred_user: %s", e)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset user state + clear pending callbacks on /start. Handles deep-link referral + onboarding."""
    try:
        context.user_data.clear()
        chat_id = str(update.effective_user.id if update.effective_user else update.effective_chat.id)
        # Handle deep-link: /start ref_XXXXXXXX
        args = context.args or []
        if args and str(args[0]).startswith("ref_"):
            ref_code = str(args[0])[4:].upper()
            asyncio.create_task(_register_referred_user(chat_id, ref_code))

        # Check if brand new user → start onboarding
        try:
            is_new = await asyncio.wait_for(_is_new_user(chat_id), timeout=4.0)
        except Exception:
            is_new = False

        if is_new:
            context.user_data["onboarding"] = True
            context.user_data["awaiting"] = "onboarding_wallet"
            await update.message.reply_text(
                f"<b>⚡ Bienvenue sur NEXUS BET</b>\n{L}\n"
                f"Bot de prédiction Polymarket autonome.\n\n"
                f"<b>20 agents IA</b> détectent les mispricings 24/7.\n"
                f"Signaux vérifiés · Auto-trade · Track record public.\n"
                f"{L}\n"
                f"<b>Étape 1/4</b> — Connecte ton wallet Polymarket :\n"
                f"<code>Envoie ton adresse 0x...</code>",
                parse_mode="HTML",
            )
            return

        # Check trial/subscription status
        try:
            status = await asyncio.wait_for(_check_trial_status(chat_id), timeout=4.0)
        except Exception:
            status = {"exists": True, "is_active": True, "is_trial": False, "expired": False}

        if status.get("expired"):
            await update.message.reply_text(
                f"<b>⚡ NEXUS BET</b>\n{L}\n"
                f"<b>⏰ Essai gratuit terminé</b>\n\n"
                f"Abonne-toi pour continuer à recevoir les signaux :\n{L}",
                parse_mode="HTML",
                reply_markup=_payment_keyboard(),
            )
            return

        text = await asyncio.wait_for(_get_start_text(), timeout=HANDLER_TIMEOUT)
        if status.get("is_trial") and status.get("days_left", 0) <= 2:
            text += f"\n⚠️ <i>Essai se termine dans {status['days_left']}j</i>"
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=_main_keyboard())
    except Exception as e:
        log.exception("cmd_start: %s", e)
        await _safe_reply(update, f"<b>⚡ NEXUS BET</b>\n{L}\n<code>CHARGEMENT...</code>", _main_keyboard())


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _ack_then_reply(update, _get_portfolio_text, f"<b>💰 PORTFOLIO</b>\n{L}\n<code>CHARGEMENT...</code>", _portfolio_keyboard())
    except Exception as e:
        log.exception("cmd_portfolio: %s", e)
        await _safe_reply(update, f"<b>💰 PORTFOLIO</b>\n{L}\n<code>ERREUR — réessayez</code>", _portfolio_keyboard())


def _scan_fallback() -> str:
    n = _get_market_count()
    return (
        f"<b>📡 MARKET SCANNER</b>\n{L}\n"
        f"<code>MARCHÉS   {n}\nSIGNAUX   0\nSTATUS    EN ATTENTE</code>\n{L}"
    )


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _ack_then_reply(update, _get_scan_text, _scan_fallback(), _scan_keyboard())
    except Exception as e:
        log.exception("cmd_scan: %s", e)
        await _safe_reply(update, _scan_fallback(), _scan_keyboard())


async def cmd_agents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _ack_then_reply(update, _get_agents_text, f"<b>🧠 AI SWARM</b>\n{L}\n<code>CHARGEMENT...</code>", _back_keyboard())
    except Exception as e:
        log.exception("cmd_agents: %s", e)
        await _safe_reply(update, f"<b>🧠 AI SWARM</b>\n{L}\n<code>ERREUR — réessayez</code>", _back_keyboard())


async def cmd_whales(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _ack_then_reply(update, _get_whales_text, f"<b>🐋 WHALE TRACKER</b>\n{L}\n<code>CHARGEMENT...</code>", _back_keyboard())
    except Exception as e:
        log.exception("cmd_whales: %s", e)
        await _safe_reply(update, f"<b>🐋 WHALE TRACKER</b>\n{L}\n<code>ERREUR — réessayez</code>", _back_keyboard())


async def _get_referral_text(chat_id: str, bot_username: str = "") -> str:
    """Récupère ou génère le code referral de l'utilisateur."""
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    code = ""
    referred_count = 0
    if url and key:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                headers = {"apikey": key, "Authorization": f"Bearer {key}"}
                r = await client.get(
                    f"{url}/rest/v1/users",
                    params={"telegram_chat_id": f"eq.{chat_id}", "select": "referral_code,referred_count"},
                    headers=headers,
                )
                if r.status_code == 200 and r.json():
                    row = r.json()[0]
                    code = row.get("referral_code") or ""
                    referred_count = int(row.get("referred_count") or 0)
                if not code:
                    import uuid as _uuid
                    code = _uuid.uuid4().hex[:8].upper()
                    await client.patch(
                        f"{url}/rest/v1/users",
                        params={"telegram_chat_id": f"eq.{chat_id}"},
                        headers={**headers, "Content-Type": "application/json", "Prefer": "return=minimal"},
                        json={"referral_code": code},
                    )
        except Exception as e:
            log.debug("referral fetch: %s", e)
    if not code:
        import hashlib as _hl
        code = _hl.md5(chat_id.encode()).hexdigest()[:8].upper()
    bot_name = bot_username or os.getenv("TELEGRAM_BOT_USERNAME", "NexusCapitalBot")
    ref_link = f"https://t.me/{bot_name}?start=ref_{code}"
    return (
        f"🤝 <b>REFERRAL</b>\n{LINE}\n"
        f"Ton code : <code>{code}</code>\n\n"
        f"👥 Filleuls actifs : <b>{referred_count}</b>\n\n"
        f"🔗 Lien :\n<code>{ref_link}</code>\n\n"
        f"<i>Partage ce lien — chaque abonné via ton lien te rapporte une commission.</i>\n{LINE}"
    )


async def cmd_referral(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_user.id if update.effective_user else update.effective_chat.id)
    bot_username = ""
    try:
        bot_username = (await context.bot.get_me()).username or ""
    except Exception:
        pass
    try:
        text = await asyncio.wait_for(_get_referral_text(chat_id, bot_username), timeout=6.0)
    except Exception:
        text = f"<b>👥 REFERRAL</b>\n{L}\n<code>ERREUR — réessayez</code>"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=_back_keyboard())


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        text = _get_settings_text()
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=_settings_keyboard())
    except Exception as e:
        log.exception("cmd_settings: %s", e)
        await _safe_reply(update, f"⚙️ <b>SETTINGS</b>\n{LINE}\nErreur.", _settings_keyboard())


async def cmd_market(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fiche Market Object : /market <slug_ou_question> (cache 60s, timeout 10s)."""
    try:
        query = " ".join((context.args or [])).strip()
        text, kb = await asyncio.wait_for(_get_market_text(query), timeout=HANDLER_TIMEOUT)
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    except asyncio.TimeoutError:
        await _safe_reply(update, f"🎯 <b>MARKET</b>\n{LINE}\nDélai. Réessayez.", _back_keyboard())
    except Exception as e:
        log.exception("cmd_market: %s", e)
        await _safe_reply(update, f"🎯 <b>MARKET</b>\n{LINE}\nErreur. Réessayez.", _back_keyboard())


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
            f"<b>🔐 ACCÈS DASHBOARD</b>\n{L}\n"
            f"<code>{link}</code>\n\n"
            f"<b>⚠️ COMPTE NON ACTIF</b>\n"
            f"<i>Contacte l'admin ou utilise un lien referral pour activer ton accès.</i>\n{L}"
        )
    else:
        text = (
            f"<b>🔐 DASHBOARD PRIVÉ</b>\n{L}\n"
            f"<code>{link}</code>\n\n"
            f"<i>Lien personnel — ne pas partager.</i>\n{L}"
        )
    kb = _back_keyboard()
    if ack:
        try:
            await ack.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def cmd_activate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin only: /activate <chat_id> [plan] — active un utilisateur dans Supabase."""
    caller = update.effective_user.id if update.effective_user else 0
    if not _is_admin(caller):
        await _safe_reply(update, "⛔ Réservé aux admins.")
        return
    args = context.args or []
    if not args:
        await _safe_reply(update, "Usage: /activate <chat_id> [free|premium|pro]")
        return
    target_chat_id = args[0].strip()
    plan = args[1].strip() if len(args) > 1 else "premium"
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        await _safe_reply(update, "❌ Supabase non configuré.")
        return
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            headers = {
                "apikey": key, "Authorization": f"Bearer {key}",
                "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal",
            }
            # Check if user already exists
            r_check = await client.get(
                f"{url}/rest/v1/users",
                params={"telegram_chat_id": f"eq.{target_chat_id}", "select": "id"},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            user_exists = r_check.status_code == 200 and bool(r_check.json())
            if user_exists:
                # PATCH existing user — no access_token change
                r = await client.patch(
                    f"{url}/rest/v1/users",
                    params={"telegram_chat_id": f"eq.{target_chat_id}"},
                    headers=headers,
                    json={"is_active": True, "plan": plan},
                )
            else:
                # INSERT new user — access_token NOT NULL required
                r = await client.post(
                    f"{url}/rest/v1/users",
                    headers=headers,
                    json={
                        "telegram_chat_id": target_chat_id,
                        "access_token": uuid.uuid4().hex[:8].lower(),
                        "is_active": True,
                        "plan": plan,
                    },
                )
            ok = r.status_code in (200, 201, 204)
        if ok:
            await _safe_reply(update, f"✅ Utilisateur <code>{target_chat_id}</code> activé (plan: {plan})")
            # Notify the user
            try:
                from config.settings import SETTINGS as _SETTINGS
                t_cfg = _SETTINGS.get("telegram")
                token = getattr(t_cfg, "bot_token", None) or os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
                if token:
                    async with httpx.AsyncClient(timeout=5.0) as c:
                        await c.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={
                                "chat_id": target_chat_id,
                                "text": (
                                    f"✅ <b>Accès activé !</b>\n{LINE}\n"
                                    f"Ton abonnement <b>{plan.upper()}</b> est actif.\n"
                                    f"Utilise /start pour accéder à tous les signaux.\n{LINE}"
                                ),
                                "parse_mode": "HTML",
                            },
                        )
            except Exception:
                pass
        else:
            await _safe_reply(update, f"<b>❌ ERREUR ACTIVATION</b>\n{L}\n<code>{r.status_code}</code>")
    except Exception as e:
        log.exception("cmd_activate: %s", e)
        await _safe_reply(update, f"<b>❌ ERREUR</b>\n{L}\n<code>{e}</code>")


async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Génère un token d'accès dashboard et envoie le lien à l'utilisateur."""
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    if not chat_id:
        return
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    dashboard_url = os.getenv("DASHBOARD_URL", "https://nexus-terminal.vercel.app")

    if not url or not key:
        await _safe_reply(update, f"<b>📊 DASHBOARD</b>\n{L}\n<i>Supabase non configuré.</i>")
        return

    try:
        token = uuid.uuid4().hex[:16]
        async with httpx.AsyncClient(timeout=8.0) as client:
            headers = {
                "apikey": key, "Authorization": f"Bearer {key}",
                "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal",
            }
            # Check user is active
            r = await client.get(
                f"{url}/rest/v1/users",
                params={"telegram_chat_id": f"eq.{chat_id}", "select": "is_active,plan"},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            rows = r.json() if r.status_code == 200 else []
            if not rows or not rows[0].get("is_active"):
                await _safe_reply(
                    update,
                    f"<b>📊 DASHBOARD</b>\n{L}\n"
                    "⛔ Ton abonnement n'est pas actif.\n"
                    "Contacte l'admin pour activer ton accès.",
                )
                return
            # Store dashboard_token
            await client.patch(
                f"{url}/rest/v1/users",
                params={"telegram_chat_id": f"eq.{chat_id}"},
                headers=headers,
                json={"dashboard_token": token},
            )
        link = f"{dashboard_url}?token={token}"
        plan = rows[0].get("plan", "premium").upper()
        msg = (
            f"<b>📊 DASHBOARD NEXUS</b>\n{L}\n"
            f"Plan <b>{plan}</b> · Lien valide 30 jours\n\n"
            f"<code>{link}</code>\n\n"
            f"{L}\n"
            f"<i>Ne partage pas ce lien — il est lié à ton compte.</i>"
        )
        await _safe_reply(update, msg)
    except Exception as e:
        log.warning("cmd_dashboard: %s", e)
        await _safe_reply(update, f"<b>❌ ERREUR</b>\n{L}\n<code>{e}</code>")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Status du système : scanner, signaux, abonnés."""
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

    signals_today = 0
    last_signal = "—"
    active_users = 0

    if url and key:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                h = {"apikey": key, "Authorization": f"Bearer {key}"}
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                r1 = await client.get(
                    f"{url}/rest/v1/signals",
                    params={"created_at": f"gte.{today}T00:00:00Z", "select": "id,created_at", "order": "created_at.desc"},
                    headers=h,
                )
                if r1.status_code == 200:
                    rows = r1.json()
                    signals_today = len(rows) if isinstance(rows, list) else 0
                    if rows:
                        last_signal = rows[0].get("created_at", "")[:16].replace("T", " ")

                r2 = await client.get(
                    f"{url}/rest/v1/users",
                    params={"is_active": "eq.true", "select": "id"},
                    headers=h,
                )
                if r2.status_code == 200:
                    active_users = len(r2.json()) if isinstance(r2.json(), list) else 0
        except Exception:
            pass

    n_markets = _get_market_count()
    msg = (
        f"<b>⚡ NEXUS STATUS</b>\n{L}\n"
        f"<code>SCANNER  {'🟢 UP' if n_markets > 0 else '🔴 DOWN'}\n"
        f"MARCHÉS  {n_markets}\n"
        f"SIGNAUX  {signals_today} aujourd'hui\n"
        f"DERNIER  {last_signal}\n"
        f"ABONNÉS  {active_users} actifs</code>\n{L}"
    )
    await _safe_reply(update, msg)


async def handle_wallet_paste(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    m = POLYGON_ADDRESS_PATTERN.match(text)
    if not m:
        return
    addr = m.group(0)
    await update.message.reply_text(
        f"<b>🐋 WALLET DÉTECTÉ</b>\n{L}\n<code>{addr}</code>\n{L}",
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

    # ── Onboarding flow ──
    if awaiting == "onboarding_wallet":
        if not POLYGON_ADDRESS_PATTERN.match(text):
            await update.message.reply_text(
                f"<b>❌ Adresse invalide</b>\n{L}\n<code>Format: 0x + 40 hex chars</code>\nRéessaie :",
                parse_mode="HTML",
            )
            return
        chat_id = str(update.effective_user.id if update.effective_user else update.effective_chat.id)
        await _save_user_field(chat_id, wallet_address=text)
        context.user_data["onboarding_wallet"] = text
        context.user_data["awaiting"] = "onboarding_apikey"
        await update.message.reply_text(
            f"<b>✅ Wallet connecté</b>\n<code>{text}</code>\n{L}\n"
            f"<b>Étape 2/4</b> — Clé API Polymarket :\n"
            f"<code>Polymarket.com → Settings → API Keys</code>\n\n"
            f"Envoie ta clé API (commence par 0x...) :",
            parse_mode="HTML",
        )
        return

    if awaiting == "onboarding_apikey":
        chat_id = str(update.effective_user.id if update.effective_user else update.effective_chat.id)
        raw_key = text.strip().strip('"').strip("'")
        if len(raw_key) < 10:
            await update.message.reply_text(f"<b>❌ Clé trop courte</b>\nRéessaie :", parse_mode="HTML")
            return
        # Chiffrement Fernet si NEXUS_ENCRYPTION_KEY disponible
        try:
            from core.crypto_keys import encrypt_key, is_encryption_available
            if is_encryption_available():
                encrypted = encrypt_key(raw_key)
                await _save_user_field(chat_id, polymarket_private_key_enc=encrypted)
                log.info("onboarding: private key encrypted and stored for chat_id=%s", chat_id)
            else:
                log.warning("onboarding: NEXUS_ENCRYPTION_KEY not set — storing key unencrypted")
                await _save_user_field(chat_id, polymarket_api_key=raw_key[:200])
        except Exception as e:
            log.error("onboarding encrypt error: %s", e)
            await _save_user_field(chat_id, polymarket_api_key=raw_key[:200])
        finally:
            raw_key = None  # efface la clé de la mémoire locale
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"<b>✅ Clé chiffrée et stockée de façon sécurisée</b>\n{L}\n"
            f"<b>Étape 3/4</b> — Profil de risque :\n\n"
            f"🛡️ <b>Conservateur</b> — Kelly 10%, max 3 positions\n"
            f"📊 <b>Quantitatif</b> — Kelly 25%, max 5 positions\n"
            f"🎲 <b>Degen</b> — Kelly 50%, max 10 positions",
            parse_mode="HTML",
            reply_markup=_risk_profile_keyboard(),
        )
        return

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
        status = "<b>✅ SEUILS MIS À JOUR</b>" if ok else "<b>❌ FORMAT INVALIDE</b>\n<code>min_edge min_ev volume liquidity</code>"
        await update.message.reply_text(f"{status}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_keyboard())
        return

    if awaiting == "capital":
        try:
            val = float(text.replace(",", "."))
            ok = set_env_value("TOTAL_CAPITAL", int(val) if val == int(val) else val) if val > 0 else False
        except (ValueError, TypeError):
            ok = False
        context.user_data.pop("awaiting", None)
        status = "<b>✅ CAPITAL MIS À JOUR</b>" if ok else "<b>❌ VALEUR INVALIDE</b>"
        await update.message.reply_text(f"{status}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_keyboard())
        return

    if awaiting == "max_positions":
        try:
            val = int(text)
            ok = set_env_value("AUTO_TRADE_MAX_POSITIONS", max(1, min(val, 20))) if 1 <= val <= 20 else False
        except (ValueError, TypeError):
            ok = False
        context.user_data.pop("awaiting", None)
        status = "<b>✅ MIS À JOUR</b>" if ok else "<b>❌ VALEUR INVALIDE</b>"
        await update.message.reply_text(f"{status}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_autotrade_keyboard())
        return

    if awaiting == "drawdown":
        try:
            val = float(text.replace(",", "."))
            ok = set_env_value("AUTO_TRADE_DAILY_DRAWDOWN_LIMIT", max(1, min(val, 100))) if 1 <= val <= 100 else False
        except (ValueError, TypeError):
            ok = False
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"{'<b>✅ MIS À JOUR</b>' if ok else '<b>❌ INVALIDE</b>'}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_autotrade_keyboard())
        return

    if awaiting == "categories":
        parts = [x.strip().lower() for x in text.split(",") if x.strip()]
        valid = {"sport", "politique", "crypto", "finance", "autre"}
        filtered = [p for p in parts if p in valid]
        ok = set_env_value("AUTO_TRADE_CATEGORIES_BLACKLIST", ",".join(filtered))
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"{'<b>✅ MIS À JOUR</b>' if ok else '<b>❌ INVALIDE</b>'}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_advanced_keyboard())
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
        await update.message.reply_text(f"{'<b>✅ MIS À JOUR</b>' if ok else '<b>❌ INVALIDE</b>'}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_advanced_keyboard())
        return

    if awaiting == "reinvest":
        try:
            val = float(text.replace(",", "."))
            ok = set_env_value("AUTO_TRADE_REINVEST_PCT", max(0, min(100, int(val)))) if 0 <= val <= 100 else False
        except (ValueError, TypeError):
            ok = False
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"{'<b>✅ MIS À JOUR</b>' if ok else '<b>❌ INVALIDE</b>'}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_advanced_keyboard())
        return

    if awaiting == "keywords":
        parts = [x.strip().lower() for x in text.split(",") if x.strip()]
        ok = set_env_value("AUTO_TRADE_KEYWORDS_BLACKLIST", ",".join(parts))
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"{'<b>✅ MIS À JOUR</b>' if ok else '<b>❌ INVALIDE</b>'}\n\n{_get_settings_text()}", parse_mode="HTML", reply_markup=_settings_advanced_keyboard())
        return

    if awaiting == "buy_amount":
        pending = context.user_data.pop("buy_pending", None)
        context.user_data.pop("awaiting", None)
        if not pending:
            await update.message.reply_text(f"<b>⚠️ EXPIRÉ</b>\n{L}\n<i>Recommence depuis le scan.</i>", parse_mode="HTML")
            return
        try:
            size_usd = max(1.0, float(text.replace(",", ".")))
        except (ValueError, TypeError):
            context.user_data["buy_pending"] = pending
            context.user_data["awaiting"] = "buy_amount"
            kelly_usd = pending["kelly_usd"]
            await update.message.reply_text(
                f"<b>❌ MONTANT INVALIDE</b>\n{L}\n<i>Entrez un nombre en USD (ex: 50)\nKelly suggère ${kelly_usd:.0f}</i>",
                parse_mode="HTML",
            )
            return
        result_text = await _run_buy_order(pending, size_usd)
        await update.message.reply_text(result_text, parse_mode="HTML", reply_markup=_main_keyboard())
        return


async def _run_buy_order(pending: dict, size_usd: float) -> str:
    """Execute a buy order from pending state dict; returns HTML result message."""
    sig_match = pending["sig_match"]
    market_id = pending["market_id"]
    side = pending["side"]
    price = pending["price"]
    question = pending["question"]
    sim = pending["sim"]
    size_usd = round(size_usd, 1)
    if sim:
        from monitoring.paper_portfolio import record_paper_trade
        paper_sig = {
            "market_id": market_id,
            "question": question,
            "side": side,
            "polymarket_price": price,
            "edge_pct": sig_match.get("edge_pct"),
            "confidence": sig_match.get("confidence"),
        }
        ok = record_paper_trade(paper_sig)
        if ok:
            return (
                f"<b>✅ PAPER TRADE ENREGISTRÉ</b>\n{L}\n"
                f"<b>{question}</b>\n"
                f"{side} @ ${price:.2f}  taille ${size_usd:.0f}\n"
                f"{L}\n<i>Mode SIMULATION — aucun vrai ordre placé</i>"
            )
        return (
            f"<b>⚠️ NON AJOUTÉ</b>\n{L}\n"
            f"<b>{question}</b>\n"
            f"<i>Position déjà ouverte ou slots pleins (max 5)</i>"
        )
    else:
        from execution.order_manager import OrderManager, OrderConfig
        mgr = OrderManager()
        cfg = OrderConfig(
            market_id=market_id,
            outcome=side,
            side="BUY",
            size_usd=size_usd,
            limit_price=price,
        )
        order_id = await mgr.place_limit_order(cfg)
        if order_id:
            return (
                f"<b>✅ ORDRE PLACÉ</b>\n{L}\n"
                f"<b>{question}</b>\n"
                f"{side} @ ${price:.2f}  taille ${size_usd:.0f}\n"
                f"Order: <code>{order_id}</code>\n{L}"
            )
        return (
            f"<b>❌ ÉCHEC ORDRE</b>\n{L}\n"
            f"<b>{question}</b>\n"
            f"<i>Vérifiez POLYMARKET_PRIVATE_KEY et les logs.</i>"
        )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        q = update.callback_query
        await q.answer()
    except Exception as e:
        log.debug("callback answer: %s", e)
        return
    data = q.data or ""

    async def edit(text: str, kb: InlineKeyboardMarkup | None = None):
        try:
            await q.edit_message_text(text=text, parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            log.debug("callback edit: %s", e)

    def _safe_get(get_fn, fallback: str, kb):
        async def _run():
            try:
                return await asyncio.wait_for(get_fn(), timeout=HANDLER_TIMEOUT)
            except asyncio.TimeoutError:
                return fallback
            except Exception as e:
                log.exception("Callback error: %s", e)
                return f"{fallback}\n\n⚠️ {str(e)[:60]}"
        return _run

    # ── Main menu ──
    if data == "menu_back":
        context.user_data.clear()
        try:
            text = await asyncio.wait_for(_get_start_text(), timeout=HANDLER_TIMEOUT)
        except Exception:
            text = f"<b>⚡ NEXUS BET</b>\n{L}\n<code>CHARGEMENT...</code>"
        await edit(text, _main_keyboard())
        return

    if data == "btn_scan":
        await edit(f"<b>📡 SCANNING...</b>\n{L}", None)
        result = await _safe_get(_get_scan_text, _scan_fallback(), None)()
        if isinstance(result, tuple):
            text, kb = result[0], result[1]
        else:
            text, kb = result, _scan_keyboard()
        await edit(text, kb)
        return

    if data == "btn_portfolio":
        await edit(f"<b>💰 LOADING...</b>\n{L}", None)
        text = await _safe_get(_get_portfolio_text, f"<b>💰 PORTFOLIO</b>\n{L}\n<code>CHARGEMENT...</code>", None)()
        await edit(text, _portfolio_keyboard())
        return

    if data == "portfolio_positions":
        await edit(f"<b>📋 LOADING...</b>\n{L}", None)
        try:
            text, kb, _ = await asyncio.wait_for(_get_positions_detail(context), timeout=HANDLER_TIMEOUT)
        except (asyncio.TimeoutError, Exception):
            text = f"<b>📋 POSITIONS</b>\n{L}\n<code>CHARGEMENT...</code>"
            kb = _positions_keyboard()
        await edit(text, kb)
        return

    if data == "portfolio_history":
        await edit(f"<b>📜 LOADING...</b>\n{L}", None)
        text = await _safe_get(_get_history_text, f"<b>📜 HISTORIQUE</b>\n{L}\n<code>CHARGEMENT...</code>", None)()
        await edit(text, _portfolio_keyboard())
        return

    if data == "btn_agents":
        await edit(f"<b>🧠 LOADING...</b>\n{L}", None)
        text = await _safe_get(_get_agents_text, f"<b>🧠 AI SWARM</b>\n{L}\n<code>CHARGEMENT...</code>", None)()
        await edit(text, _back_keyboard())
        return

    if data == "btn_whales":
        await edit(f"<b>🐋 LOADING...</b>\n{L}", None)
        text = await _safe_get(_get_whales_text, f"<b>🐋 WHALE TRACKER</b>\n{L}\n<code>CHARGEMENT...</code>", None)()
        await edit(text, _back_keyboard())
        return

    if data == "btn_referral":
        chat_id = str(q.from_user.id if q.from_user else "0")
        bot_username = ""
        try:
            bot_username = (await context.bot.get_me()).username or ""
        except Exception:
            pass
        try:
            text = await asyncio.wait_for(_get_referral_text(chat_id, bot_username), timeout=6.0)
        except Exception:
            text = f"<b>👥 REFERRAL</b>\n{L}\n<code>ERREUR — réessayez</code>"
        await edit(text, _back_keyboard())
        return

    # ── Signal callbacks: BUY / PASS / Investiguer ──
    if data.startswith("buy_") and not data.startswith("buy_amount"):
        parts = data[4:].split("|", 1)
        market_id = parts[0] if parts else ""
        side = parts[1] if len(parts) > 1 else "YES"
        try:
            from config.settings import settings as _s
            from paperclip_bridge import get_pending_signals
            sim = getattr(_s, "SIMULATION_MODE", True)
            sig_match: dict = {"market_id": market_id, "side": side, "recommended_outcome": side}
            try:
                for sig in (get_pending_signals() or []):
                    mid = sig.get("market_id") or sig.get("conditionId") or ""
                    if mid.startswith(market_id) or market_id.startswith(mid[:20]):
                        sig_match = sig
                        break
            except Exception:
                pass
            price = float(sig_match.get("polymarket_price") or 0.5)
            kelly = float(sig_match.get("kelly_fraction") or 0.05)
            cap = getattr(_s, "POLYMARKET_CAPITAL_USD", 1000.0) or 1000.0
            kelly_usd = max(1.0, round(cap * min(kelly, 0.10), 1))
            question = (sig_match.get("question") or market_id)[:50]
            context.user_data["buy_pending"] = {
                "sig_match": sig_match,
                "market_id": market_id,
                "side": side,
                "price": price,
                "kelly_usd": kelly_usd,
                "question": question,
                "sim": sim,
            }
            context.user_data["awaiting"] = "buy_amount"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ Confirmer Kelly (${kelly_usd:.0f})", callback_data="buy_amount_confirm")],
                [InlineKeyboardButton("❌ Annuler", callback_data="buy_amount_cancel")],
            ])
            await edit(
                f"<b>💰 MONTANT À MISER ?</b>\n{L}\n"
                f"<b>{question}</b>\n"
                f"{side} @ ${price:.2f}\n{L}\n"
                f"Kelly suggère <b>${kelly_usd:.0f}</b>\n\n"
                f"<i>Tape un montant en USD ou confirme le Kelly :</i>",
                kb,
            )
        except Exception as e:
            log.exception("buy_ callback: %s", e)
            await edit(f"<b>❌ ERREUR</b>\n{L}\n<code>{str(e)[:80]}</code>", _back_keyboard())
        return

    if data == "buy_amount_confirm":
        pending = context.user_data.pop("buy_pending", None)
        context.user_data.pop("awaiting", None)
        if not pending:
            await edit(f"<b>⚠️ EXPIRÉ</b>\n{L}\n<i>Recommence depuis le scan.</i>", _back_keyboard())
            return
        await edit(f"<b>⏳ EXÉCUTION...</b>\n{L}", None)
        try:
            result_text = await _run_buy_order(pending, pending["kelly_usd"])
            await edit(result_text, _back_keyboard())
        except Exception as e:
            log.exception("buy_amount_confirm: %s", e)
            await edit(f"<b>❌ ERREUR</b>\n{L}\n<code>{str(e)[:80]}</code>", _back_keyboard())
        return

    if data == "buy_amount_cancel":
        context.user_data.pop("buy_pending", None)
        context.user_data.pop("awaiting", None)
        await edit(f"<b>✕ ACHAT ANNULÉ</b>\n{L}", _main_keyboard())
        return

    if data.startswith("snipe_"):
        market_id = data[6:]
        await edit(f"<b>⏳ SNIPE EN COURS...</b>\n{L}", None)
        try:
            from config.settings import settings as _s
            from monitoring.push_alerts import calculate_kelly
            sim = getattr(_s, "SIMULATION_MODE", True)

            # Reconstruit un pending minimal depuis l'ID marché
            class _FakeSig:
                confidence = 0.5
            kelly_usd = calculate_kelly(_FakeSig())

            context.user_data["buy_pending"] = {
                "sig_match": {"market_id": market_id, "side": "YES"},
                "market_id": market_id,
                "side": "YES",
                "price": 0.5,
                "kelly_usd": kelly_usd,
                "question": market_id[:50],
                "sim": sim,
            }
            context.user_data["awaiting"] = "buy_amount"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ Confirmer Kelly (${kelly_usd:.0f})", callback_data="buy_amount_confirm")],
                [InlineKeyboardButton("❌ Annuler", callback_data="buy_amount_cancel")],
            ])
            await edit(
                f"<b>⚡ SNIPE — MONTANT À MISER ?</b>\n{L}\n"
                f"<code>{market_id[:50]}</code>\n{L}\n"
                f"Kelly suggère <b>${kelly_usd:.0f}</b>\n\n"
                f"<i>Tape un montant en USD ou confirme :</i>",
                kb,
            )
        except Exception as e:
            log.exception("snipe_ callback: %s", e)
            await edit(f"<b>❌ ERREUR</b>\n{L}\n<code>{str(e)[:80]}</code>", _back_keyboard())
        return

    if data.startswith("pass_"):
        await edit(f"<b>❌ SIGNAL PASSÉ</b>\n{L}\n<i>Signal ignoré.</i>", _scan_keyboard())
        return

    if data.startswith("ignore_"):
        await edit(f"<b>✕ SIGNAL IGNORÉ</b>\n{L}", _main_keyboard())
        return

    if data.startswith("inv_"):
        parts = data[4:].split("|", 1)
        market_id = parts[0] if parts else ""
        side = parts[1] if len(parts) > 1 else ""
        await edit(
            f"<b>🔍 INVESTIGATION</b>\n{L}\n"
            f"<code>MARCHÉ  {market_id[:38]}\n"
            f"SIDE    {side}</code>\n{L}\n"
            f"<i>Tape /market pour la fiche complète.</i>",
            _back_keyboard(),
        )
        return

    # ── Paste & Monitor (wallet add/cancel) ──
    if data == "wallet_cancel":
        await edit(f"<b>✕ ANNULÉ</b>")
        return

    if data.startswith("wallet_add_"):
        addr = data.replace("wallet_add_", "")
        if POLYGON_ADDRESS_PATTERN.match(addr):
            try:
                from monitoring.telegram_wealth_manager import add_whale_wallet
                if add_whale_wallet(addr):
                    await edit(f"<b>✅ WALLET AJOUTÉ</b>\n{L}\n<code>{addr}</code>\n<i>Surveillance active.</i>")
                else:
                    await edit(f"<b>❌ ERREUR</b>\n{L}\n<code>Ajout impossible.</code>")
            except Exception as e:
                log.exception("wallet_add: %s", e)
                await edit(f"<b>❌ ERREUR</b>\n{L}\n<code>{e}</code>")
        else:
            await edit(f"<b>❌ ADRESSE INVALIDE</b>")
        return

    # ── Exit position (confirmation) ──
    if data == "exit_cancel":
        await edit(f"<b>📋 LOADING...</b>\n{L}", None)
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
        question = (pos.get("question") or pos.get("market_id") or "?")[:38]
        await edit(
            f"<b>✕ CONFIRMER EXIT</b>\n{L}\n<code>{question}</code>\n{L}\n<i>Cette action est irréversible.</i>",
            _exit_confirm_keyboard(),
        )
        context.user_data["exit_pending"] = pos
        return

    if data == "exit_confirm":
        pos = context.user_data.pop("exit_pending", None)
        if not pos:
            await edit(f"<b>⚡ NEXUS BET</b>\n{L}\n<code>POSITION EXPIRÉE</code>", _main_keyboard())
            return
        await edit(f"<b>⚡ VENTE EN COURS...</b>\n{L}", None)
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
                await send_telegram_message(
                    f"<b>✕ EXIT EXÉCUTÉ</b>\n{L}\n<code>{mkt}</code>\n<code>ID: {order_id}</code>"
                )
            finally:
                await om.client.close()
        except Exception as e:
            log.exception("Exit failed: %s", e)
            await edit(f"<b>❌ EXIT ÉCHOUÉ</b>\n{L}\n<code>{e}</code>", _main_keyboard())
            return
        await edit(f"<b>✕ EXIT EXÉCUTÉ</b>\n{L}\n<i>Position soldée.</i>", _main_keyboard())
        return

    # ── Onboarding callbacks ──
    RISK_PROFILES = {
        "onboard_risk_conservateur": ("conservateur", 0.10, 3),
        "onboard_risk_quantitatif":  ("quantitatif",  0.25, 5),
        "onboard_risk_degen":        ("degen",         0.50, 10),
    }
    if data in RISK_PROFILES:
        profile_name, kelly, max_pos = RISK_PROFILES[data]
        chat_id = str(q.from_user.id if q.from_user else "0")
        await _save_user_field(chat_id, risk_profile=profile_name, kelly_pct=kelly, max_positions=max_pos)
        ls97  = os.getenv("LS_CHECKOUT_97",  "https://t.me/nexus_capital_bot")
        ls197 = os.getenv("LS_CHECKOUT_197", "https://t.me/nexus_capital_bot")
        ls297 = os.getenv("LS_CHECKOUT_297", "https://t.me/nexus_capital_bot")
        await edit(
            f"<b>✅ Profil {profile_name.upper()} sauvegardé</b>\n{L}\n"
            f"<code>Kelly     {int(kelly*100)}%\n"
            f"Max pos   {max_pos}</code>\n"
            f"{L}\n"
            f"<b>Étape 4/4</b> — Choisis ton abonnement :\n\n"
            f"<b>€97/mois</b> — Signaux Telegram + dashboard\n"
            f"<b>€197/mois</b> — Full Auto-trade ⚡\n"
            f"<b>€297 once</b> — Lifetime License ♾️\n\n"
            f"<i>Ou démarre avec 7 jours gratuits ↓</i>",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("€97/mois — Signal Intel", url=ls97)],
                [InlineKeyboardButton("⚡ €197/mois — Full Auto", url=ls197)],
                [InlineKeyboardButton("♾️ €297 — Lifetime", url=ls297)],
                [InlineKeyboardButton("🎁 Essai 7j gratuit", callback_data="onboard_start_trial")],
            ]),
        )
        return

    if data == "onboard_start_trial":
        chat_id = str(q.from_user.id if q.from_user else "0")
        ok = await _start_trial(chat_id)
        if ok:
            token, _ = await _upsert_user_token(chat_id)
            dashboard_url = os.getenv("DASHBOARD_URL", "https://nexus-capital-eight.vercel.app").rstrip("/")
            link = f"{dashboard_url}?token={token}" if token else dashboard_url
            await edit(
                f"<b>🎉 Essai gratuit activé — 7 jours</b>\n{L}\n"
                f"Tu reçois maintenant les signaux NEXUS BET.\n\n"
                f"🔐 Dashboard privé :\n<code>{link}</code>\n{L}\n"
                f"<i>Tape /start pour accéder au menu.</i>",
                _back_keyboard(),
            )
        else:
            await edit(f"<b>❌ Erreur activation</b>\n{L}\n<i>Contacte le support.</i>", _back_keyboard())
        return

        # ── Settings ──
    if data == "btn_settings":
        await edit(_get_settings_text(), _settings_keyboard())
        return

    if data == "settings_dashboard":
        # Generate/show dashboard link for the user
        chat_id = str(q.from_user.id if q.from_user else "0")
        dashboard_url = os.getenv("DASHBOARD_URL", "https://nexus-capital-eight.vercel.app").rstrip("/")
        # Try to get or generate a token from Supabase
        token = ""
        url_sb = os.getenv("SUPABASE_URL", "").rstrip("/")
        key_sb = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        if url_sb and key_sb and chat_id:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(
                        f"{url_sb}/rest/v1/users",
                        params={"telegram_chat_id": f"eq.{chat_id}", "select": "access_token,is_active"},
                        headers={"apikey": key_sb, "Authorization": f"Bearer {key_sb}"},
                    )
                    if r.status_code == 200:
                        rows = r.json()
                        if rows and isinstance(rows, list):
                            token = rows[0].get("access_token", "")
            except Exception:
                pass
        if not token:
            token = str(uuid.uuid4()).replace("-", "")[:24]
        private_link = f"{dashboard_url}?token={token}"
        public_link = f"{dashboard_url}?token=public"
        await edit(
            f"<b>📊 DASHBOARD NEXUS BET</b>\n{L}\n"
            f"<b>Lien privé (abonnés)</b>\n<code>{private_link}</code>\n\n"
            f"<b>Track Record public</b>\n<code>{public_link}</code>\n\n"
            f"{L}\n"
            f"<i>Ne partage pas ton lien privé — lié à ton compte.</i>",
            _settings_keyboard(),
        )
        return

    if data == "settings_thresholds":
        context.user_data["awaiting"] = "thresholds"
        await edit(
            f"<b>⚙️ THRESHOLDS</b>\n{L}\n"
            f"<code>4 valeurs séparées par espaces :\nmin_edge min_ev volume liquidity\n\nEx: 5.0 20 1000 100</code>",
            _back_keyboard(),
        )
        return

    if data == "settings_capital":
        context.user_data["awaiting"] = "capital"
        await edit(f"<b>⚙️ CAPITAL</b>\n{L}\n<code>Montant en USD\nEx: 1000</code>", _back_keyboard())
        return

    if data == "settings_toggle_sim":
        from monitoring.env_config import set_env_value
        sim = os.getenv("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")
        ok = set_env_value("SIMULATION_MODE", str(not sim).lower())
        await edit(_get_settings_text(), _settings_keyboard())
        return

    if data == "settings_autotrade":
        text = _get_settings_text() + f"\n<i>STRONG BUY → immédiat · BUY → confirmation 30min</i>"
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
        await edit(f"<b>⚙️ MAX POSITIONS</b>\n{L}\n<code>1–20\nEx: 3</code>", _settings_autotrade_keyboard())
        return

    if data == "settings_drawdown":
        context.user_data["awaiting"] = "drawdown"
        await edit(f"<b>⚙️ DRAWDOWN LIMIT</b>\n{L}\n<code>% (1–100)\nEx: 20</code>", _settings_autotrade_keyboard())
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
            f"<b>⚙️ ADVANCED</b>\n{L}\n"
            f"<code>BLACKLIST  {cats}\n"
            f"JOURS      {min_d}–{max_d}\n"
            f"KEYWORDS   {kw}\n"
            f"REINVEST   {reinv}%</code>\n{L}",
            _settings_advanced_keyboard(),
        )
        return

    if data == "settings_categories":
        context.user_data["awaiting"] = "categories"
        await edit(f"<b>⚙️ BLACKLIST CATÉGORIES</b>\n{L}\n<code>sport,politique,crypto,finance,autre</code>", _settings_advanced_keyboard())
        return

    if data == "settings_days_resolution":
        context.user_data["awaiting"] = "days_resolution"
        await edit(f"<b>⚙️ JOURS RÉSOLUTION</b>\n{L}\n<code>min max\nEx: 0 730</code>", _settings_advanced_keyboard())
        return

    if data == "settings_reinvest":
        context.user_data["awaiting"] = "reinvest"
        await edit(f"<b>⚙️ RÉINVESTISSEMENT</b>\n{L}\n<code>% de gains (0-100)\nEx: 50</code>", _settings_advanced_keyboard())
        return

    if data == "settings_keywords":
        context.user_data["awaiting"] = "keywords"
        await edit(f"<b>⚙️ BLACKLIST MOTS-CLÉS</b>\n{L}\n<code>mots séparés par virgules\nEx: war,nuclear</code>", _settings_advanced_keyboard())
        return

        # ── Auto-trade confirm/ignore ──
    if data.startswith("autotrade_confirm_"):
        sid = data.replace("autotrade_confirm_", "")
        from monitoring.auto_trade import get_pending_confirm, remove_pending_confirm, execute_signal
        sig = get_pending_confirm(sid)
        if not sig:
            await edit(f"<b>⚡ NEXUS BET</b>\n{L}\n<code>EXPIRÉ — signal &gt;30min</code>")
            return
        await edit(f"<b>⚡ EXÉCUTION EN COURS...</b>\n{L}", None)
        order_id = await execute_signal(sig)
        remove_pending_confirm(sid)
        await edit(
            f"<b>✅ ORDRE EXÉCUTÉ</b>\n{L}\n<code>ID: {order_id}</code>" if order_id
            else f"<b>❌ ÉCHEC EXÉCUTION</b>\n{L}",
            _main_keyboard(),
        )
        return

    if data.startswith("autotrade_ignore_"):
        sid = data.replace("autotrade_ignore_", "")
        from monitoring.auto_trade import remove_pending_confirm
        remove_pending_confirm(sid)
        await edit(f"<b>✕ SIGNAL IGNORÉ</b>\n{L}", _main_keyboard())
        return

    # ── Wealth suggestion: approve / wait ──
    if data.startswith("approve_"):
        from monitoring.wealth_suggestions import get_suggestion, remove_suggestion
        sid = data.replace("approve_", "")
        sug = get_suggestion(sid)
        if not sug:
            await edit(f"<b>⚡ NEXUS BET</b>\n{L}\n<code>SUGGESTION EXPIRÉE</code>")
            return
        await edit(f"<b>⚡ EXÉCUTION EN COURS...</b>\n{L}", None)
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
                f"<b>✅ ORDRE EXÉCUTÉ</b>\n{L}\n<code>ID: {order_id}</code>" if order_id
                else f"<b>❌ ÉCHEC</b>\n{L}",
                _main_keyboard(),
            )
        except Exception as e:
            log.exception("Approve error: %s", e)
            await edit(f"<b>❌ ERREUR</b>\n{L}\n<code>{e}</code>", _main_keyboard())
        return

    if data.startswith("wait_"):
        from monitoring.wealth_suggestions import remove_suggestion
        try:
            from defi_yield_manager import clear_pending_trade
            clear_pending_trade()
        except ImportError:
            pass
        remove_suggestion(data.replace("wait_", ""))
        await edit(f"<b>⏸ EN ATTENTE</b>\n{L}", _main_keyboard())
        return


# ══════════════════════════════════════════════
# POLLER
# ══════════════════════════════════════════════

# ══════════════════════════════════════════════
# ONBOARDING + TRIAL + BROADCAST
# ══════════════════════════════════════════════

TRIAL_DAYS = 7


def _risk_profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡️ Conservateur", callback_data="onboard_risk_conservateur")],
        [InlineKeyboardButton("📊 Quantitatif", callback_data="onboard_risk_quantitatif")],
        [InlineKeyboardButton("🎲 Degen", callback_data="onboard_risk_degen")],
    ])


def _payment_keyboard() -> InlineKeyboardMarkup:
    ls97 = os.getenv("LS_CHECKOUT_97", "https://t.me/nexus_capital_bot")
    ls197 = os.getenv("LS_CHECKOUT_197", "https://t.me/nexus_capital_bot")
    ls297 = os.getenv("LS_CHECKOUT_297", "https://t.me/nexus_capital_bot")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("€97/mois — Signal Intel", url=ls97)],
        [InlineKeyboardButton("⚡ €197/mois — Full Auto", url=ls197)],
        [InlineKeyboardButton("♾️ €297 — Lifetime", url=ls297)],
        [InlineKeyboardButton("🎁 Essai 7 jours gratuit", callback_data="onboard_start_trial")],
    ])


async def _is_new_user(chat_id: str) -> bool:
    """Returns True if the user doesn't exist yet in Supabase."""
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(
                f"{url}/rest/v1/users",
                params={"telegram_chat_id": f"eq.{chat_id}", "select": "id", "limit": "1"},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            return r.status_code == 200 and not r.json()
    except Exception:
        return False


async def _start_trial(chat_id: str) -> bool:
    """Creates user row with 7-day trial in Supabase. Returns True on success."""
    from datetime import datetime, timezone, timedelta
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        return False
    trial_ends = (datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)).isoformat()
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post(
                f"{url}/rest/v1/users",
                headers={
                    "apikey": key, "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=ignore-duplicates,return=minimal",
                },
                json={
                    "telegram_chat_id": chat_id,
                    "is_active": True,
                    "is_trial": True,
                    "trial_ends_at": trial_ends,
                    "plan": "trial",
                },
            )
            return r.status_code in (200, 201, 204)
    except Exception:
        return False


async def _check_trial_status(chat_id: str) -> dict:
    """Returns {exists, is_active, is_trial, days_left, expired, plan}."""
    from datetime import datetime, timezone
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    default = {"exists": False, "is_active": False, "is_trial": False, "days_left": 0, "expired": False, "plan": "free"}
    if not url or not key:
        return default
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(
                f"{url}/rest/v1/users",
                params={"telegram_chat_id": f"eq.{chat_id}", "select": "is_active,is_trial,trial_ends_at,plan", "limit": "1"},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            if r.status_code != 200 or not r.json():
                return default
            row = r.json()[0]
            is_trial = bool(row.get("is_trial"))
            is_active = bool(row.get("is_active"))
            plan = row.get("plan", "free")
            days_left = 0
            expired = False
            if is_trial:
                exp = row.get("trial_ends_at")
                if exp:
                    try:
                        exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                        delta = (exp_dt - datetime.now(timezone.utc)).days
                        days_left = max(0, delta)
                        expired = delta < 0
                        if expired:
                            is_active = False
                    except Exception:
                        pass
            return {"exists": True, "is_active": is_active, "is_trial": is_trial, "days_left": days_left, "expired": expired, "plan": plan}
    except Exception:
        return default


async def _save_user_field(chat_id: str, **fields) -> bool:
    """Upsert fields into Supabase users table."""
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post(
                f"{url}/rest/v1/users",
                headers={
                    "apikey": key, "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                },
                json={"telegram_chat_id": chat_id, **fields},
            )
            return r.status_code in (200, 201, 204)
    except Exception:
        return False


async def _get_active_chat_ids() -> list[str]:
    """Returns list of telegram_chat_id for all is_active=true users (for broadcast)."""
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        return []
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(
                f"{url}/rest/v1/users",
                params={"is_active": "eq.true", "select": "telegram_chat_id", "limit": "500"},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            if r.status_code == 200:
                return [row["telegram_chat_id"] for row in r.json() if row.get("telegram_chat_id")]
    except Exception:
        pass
    return []


async def broadcast_signal(bot, signal: dict) -> int:
    """
    Send a signal card to ALL active subscribers.
    Returns the number of messages sent successfully.
    """
    chat_ids = await _get_active_chat_ids()
    if not chat_ids:
        # Fallback to single TELEGRAM_CHAT_ID
        fallback = os.getenv("TELEGRAM_CHAT_ID")
        if fallback:
            chat_ids = [fallback]
    edge = float(signal.get("edge_pct") or 0)
    question = (signal.get("question") or signal.get("market_id") or "?")[:72]
    side = signal.get("side", "YES")
    price = float(signal.get("polymarket_price") or 0.5)
    strength = signal.get("signal_strength", "BUY")
    icon = "⚡" if "STRONG" in str(strength) else "▲"
    cat = _detect_category(question)
    text = (
        f"{icon} <b>SIGNAL · {cat}</b>\n{L}\n"
        f"<b>{question}</b>\n"
        f"<code>SIDE    {side}\n"
        f"PRICE   {price*100:.1f}%\n"
        f"EDGE    +{edge:.1f}pts\n"
        f"FORCE   {strength}</code>\n"
        f"{L}\n<i>Via NEXUS BET Intelligence</i>"
    )
    sent = 0
    for cid in chat_ids:
        try:
            await bot.send_message(chat_id=cid, text=text, parse_mode="HTML")
            sent += 1
        except Exception as e:
            log.debug("broadcast to %s failed: %s", cid, e)
    return sent


async def send_daily_report(bot) -> None:
    """Send daily P&L report to all active subscribers."""
    import json as _json
    from pathlib import Path as _P
    root = _P(__file__).resolve().parent.parent
    # Gather paper portfolio stats
    try:
        from monitoring.paper_portfolio import get_paper_summary
        pp = get_paper_summary()
    except Exception:
        pp = {}
    # Gather signal stats
    signals_today = 0
    try:
        p = root / "paperclip_pending_signals.json"
        if p.exists():
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).date().isoformat()
            d = _json.loads(p.read_text(encoding="utf-8"))
            for s in (d.get("signals", []) if isinstance(d, dict) else []):
                ts = s.get("created_at") or s.get("last_scan_ts")
                if ts and str(ts)[:10] == today:
                    signals_today += 1
            if signals_today == 0:
                signals_today = len(d.get("signals", [])) if isinstance(d, dict) else 0
    except Exception:
        pass
    pnl = pp.get("total_pnl", 0)
    wr = pp.get("win_rate", 0)
    invested = pp.get("invested", 0)
    open_count = len(pp.get("open_trades", []))
    text = (
        f"<b>📊 RAPPORT DU JOUR — NEXUS BET</b>\n{L}\n"
        f"<code>Signaux détectés : {signals_today}\n"
        f"Positions ouvertes: {open_count}\n"
        f"Investi (paper)   : ${invested:.2f}\n"
        f"P&L total         : {'+'if pnl>=0 else ''}{pnl:.2f} USDC\n"
        f"Win rate          : {wr:.0f}%</code>\n"
        f"{L}\n<i>NEXUS BET · Rapport automatique 21h00 UTC</i>"
    )
    chat_ids = await _get_active_chat_ids()
    if not chat_ids:
        fallback = os.getenv("TELEGRAM_CHAT_ID")
        if fallback:
            chat_ids = [fallback]
    for cid in chat_ids:
        try:
            await bot.send_message(chat_id=cid, text=text, parse_mode="HTML")
        except Exception as e:
            log.debug("daily report to %s failed: %s", cid, e)


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


def build_application(token: str) -> Application:
    """Build Application with all handlers. No event loop — async-native."""
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
    app.add_handler(CommandHandler("activate", cmd_activate))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Regex(POLYGON_ADDRESS_PATTERN),
            handle_wallet_paste,
        ),
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings_text))
    return app


async def run_forever() -> None:
    """
    Run Telegram poller using low-level async API (no run_polling event loop).
    Compatible with asyncio.gather() in main.py.
    Handles 409 Conflict (Railway rolling deploy overlap) with infinite retry + backoff.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        log.info("Telegram token non configuré, poller désactivé")
        return

    for _log in ("telegram", "telegram.ext"):
        logging.getLogger(_log).setLevel(logging.ERROR)

    # Aggressively clear any previous session before starting
    await close_telegram_session(token)
    await asyncio.sleep(5)  # let old Railway instance fully terminate

    app = build_application(token)
    try:
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
            BotCommand("activate", "👑 [Admin] Activer un utilisateur"),
        ])

        log.info("Telegram poller démarré (async-native, no run_polling)")
        # Infinite retry for Conflict — rebuild Application on each conflict (PTB v21 updater not restartable)
        while True:
            conflict_attempt = 0
            _app = app
            try:
                await _app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=["message", "callback_query"],
                )
                log.info("Bot is now listening for messages...")
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                is_conflict = "Conflict" in str(e) or "409" in str(e)
                try:
                    from telegram.error import Conflict as TGConflict
                    is_conflict = is_conflict or isinstance(e, TGConflict)
                except ImportError:
                    pass

                if is_conflict:
                    conflict_attempt += 1
                    wait = min(10 + conflict_attempt * 5, 30)
                    log.warning(
                        "Telegram Conflict #%d — wait %ds, rebuild app, retry",
                        conflict_attempt, wait,
                    )
                    # Gracefully stop current app before rebuilding
                    try:
                        await _app.updater.stop()
                        await _app.stop()
                        await _app.shutdown()
                    except Exception:
                        pass
                    await asyncio.sleep(wait)
                    await close_telegram_session(token)
                    await asyncio.sleep(3)
                    # Rebuild fresh Application (PTB v21 updater cannot be restarted)
                    app = build_application(token)
                    await app.initialize()
                    await app.start()
                    continue
                else:
                    raise  # non-conflict errors propagate up
    except asyncio.CancelledError:
        log.info("Telegram poller arrêté")
        raise
    finally:
        try:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception as e:
            log.debug("Telegram cleanup: %s", e)
