"""
NEXUS BET - Telegram Bot with polling and command handlers.
Handles /start, /scan, /debrief, /portfolio, /agents, /btc, /fomc
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

import httpx

from config.settings import SETTINGS

log = logging.getLogger(__name__)


def _get_token() -> Optional[str]:
    t = SETTINGS.get("telegram")
    return getattr(t, "bot_token", None) or "" if t else ""


def _get_chat_id() -> Optional[str]:
    t = SETTINGS.get("telegram")
    return getattr(t, "chat_id", None) or "" if t else ""


async def _send_reply(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, json=payload)
            return r.status_code == 200
    except Exception as e:
        log.warning("Telegram send failed: %s", e)
        return False


async def _handle_start(chat_id: str) -> str:
    return (
        "<b>NEXUS BET</b> – Prediction market trading bot\n\n"
        "Commands:\n"
        "/start – This message\n"
        "/scan – Run market scan for edges\n"
        "/debrief – AI agents debate summary\n"
        "/portfolio – Current positions & trades\n"
        "/agents – Adversarial AI team info\n"
        "/btc – BTC/crypto markets\n"
        "/fomc – FOMC-related markets"
    )


async def _handle_scan(chat_id: str) -> str:
    try:
        from data.polymarket_client import PolymarketClient
        from core.edge_engine import EdgeEngine
        from core.scanner import MarketScanner

        polymarket = PolymarketClient()
        edge_engine = EdgeEngine()
        scanner = MarketScanner(polymarket, edge_engine, on_signal=None)
        signals = await scanner._scan_once()
        await polymarket.close()

        if not signals:
            return "Scan complete. No edges found."
        lines = [f"<b>Scan:</b> {len(signals)} signal(s)\n"]
        for s in signals[:5]:
            lines.append(
                f"• {s.side} {s.market_id[:20]}... | edge {s.edge_pct:.1%} | conf {s.confidence:.0%}"
            )
        if len(signals) > 5:
            lines.append(f"... +{len(signals) - 5} more")
        return "\n".join(lines)
    except Exception as e:
        log.exception("Scan failed: %s", e)
        return f"Scan error: {e}"


async def _handle_debrief(chat_id: str) -> str:
    try:
        from agents import AdversarialAITeam

        team = AdversarialAITeam()
        if not team.api_key:
            return "ANTHROPIC_API_KEY not configured."
        return (
            "<b>Adversarial AI Team</b>\n"
            "• Quant – Proposes trades from mispricing\n"
            "• Risk Manager – Challenges every thesis\n"
            "• Head Analyst – Final approve/reject\n\n"
            "Run /scan to find signals, then agents validate before execution."
        )
    except Exception as e:
        log.exception("Debrief failed: %s", e)
        return f"Debrief error: {e}"


async def _handle_portfolio(chat_id: str) -> str:
    try:
        from monitoring.trade_logger import trade_logger

        positions = trade_logger.get_positions()
        trades = trade_logger.get_recent_trades(limit=10)
        lines = ["<b>Portfolio</b>\n"]
        if positions:
            lines.append("<b>Positions:</b>")
            for p in positions:
                lines.append(
                    f"  {p.get('market_id', '')[:25]}... | {p.get('outcome')} | "
                    f"{p.get('size', 0):.2f} @ {p.get('avg_price', 0):.2%}"
                )
        else:
            lines.append("No open positions.")
        lines.append("\n<b>Recent trades:</b>")
        if trades:
            for t in trades[:5]:
                lines.append(
                    f"  {t.get('outcome')} {t.get('size', 0):.2f} @ {t.get('price', 0):.2%}"
                )
        else:
            lines.append("No trades yet.")
        return "\n".join(lines)
    except Exception as e:
        log.exception("Portfolio failed: %s", e)
        return f"Portfolio error: {e}"


async def _handle_agents(chat_id: str) -> str:
    return (
        "<b>Adversarial AI Team</b>\n\n"
        "• <b>Quant</b> – Proposes trades from mispricing (NCAA/UCL/BTC models + Kelly)\n"
        "• <b>Risk Manager</b> – Destroys every thesis (liquidity, tail risk, slippage)\n"
        "• <b>Head Analyst</b> – Weighs both sides, APPROVE or REJECT\n\n"
        "Pipeline: Scan → Edge → Quant thesis → Risk challenge → Analyst verdict → Execute"
    )


async def _handle_btc(chat_id: str) -> str:
    try:
        from data.polymarket_client import PolymarketClient

        pm = PolymarketClient()
        markets = await pm.get_markets(limit=100)
        await pm.close()
        btc_markets = [
            m for m in markets
            if "btc" in (m.get("question") or "").lower()
            or "bitcoin" in (m.get("question") or "").lower()
            or "crypto" in (m.get("question") or "").lower()
        ]
        if not btc_markets:
            return "No BTC/crypto markets found."
        lines = [f"<b>BTC/Crypto markets:</b> {len(btc_markets)}\n"]
        for m in btc_markets[:5]:
            q = (m.get("question") or "")[:50]
            lines.append(f"• {q}...")
        if len(btc_markets) > 5:
            lines.append(f"... +{len(btc_markets) - 5} more")
        return "\n".join(lines)
    except Exception as e:
        log.exception("BTC markets failed: %s", e)
        return f"BTC error: {e}"


async def _handle_fomc(chat_id: str) -> str:
    try:
        from data.polymarket_client import PolymarketClient

        pm = PolymarketClient()
        markets = await pm.get_markets(limit=100)
        await pm.close()
        fomc_markets = [
            m for m in markets
            if "fomc" in (m.get("question") or "").lower()
            or "fed" in (m.get("question") or "").lower()
            or "rate" in (m.get("question") or "").lower()
        ]
        if not fomc_markets:
            return "No FOMC/Fed markets found."
        lines = [f"<b>FOMC/Fed markets:</b> {len(fomc_markets)}\n"]
        for m in fomc_markets[:5]:
            q = (m.get("question") or "")[:50]
            lines.append(f"• {q}...")
        if len(fomc_markets) > 5:
            lines.append(f"... +{len(fomc_markets) - 5} more")
        return "\n".join(lines)
    except Exception as e:
        log.exception("FOMC markets failed: %s", e)
        return f"FOMC error: {e}"


COMMAND_HANDLERS: dict[str, Callable[[str], Any]] = {
    "/start": _handle_start,
    "/scan": _handle_scan,
    "/debrief": _handle_debrief,
    "/portfolio": _handle_portfolio,
    "/agents": _handle_agents,
    "/btc": _handle_btc,
    "/fomc": _handle_fomc,
}


async def _process_update(token: str, update: dict) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()
    if not text or not chat_id:
        return
    cmd = text.split()[0].lower() if text else ""
    handler = COMMAND_HANDLERS.get(cmd)
    if handler:
        try:
            reply = await handler(chat_id)
            await _send_reply(token, chat_id, reply)
        except Exception as e:
            log.exception("Command %s failed: %s", cmd, e)
            await _send_reply(token, chat_id, f"Error: {e}")


async def run_telegram_poller() -> None:
    """Long-polling loop for Telegram updates."""
    token = _get_token()
    if not token:
        log.warning("Telegram token not configured, skipping poller")
        return
    log.info("Telegram poller started")
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.get(
                    url,
                    params={"offset": last_update_id + 1, "timeout": 30},
                )
            if r.status_code != 200:
                log.warning("getUpdates failed: %s", r.status_code)
                await asyncio.sleep(5)
                continue
            data = r.json()
            if not data.get("ok"):
                log.warning("getUpdates not ok: %s", data)
                await asyncio.sleep(5)
                continue
            updates = data.get("result", [])
            for u in updates:
                last_update_id = max(last_update_id, u.get("update_id", 0))
                await _process_update(token, u)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning("Poller error: %s", e)
            await asyncio.sleep(5)
    log.info("Telegram poller stopped")
