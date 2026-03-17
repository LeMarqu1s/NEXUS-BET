"""
NEXUS BET - Alertes Telegram
Notifications pour trades, erreurs et signaux.
"""
import asyncio
from typing import Optional
import httpx

from config.settings import SETTINGS


def _is_enabled() -> bool:
    t = SETTINGS.get("telegram", {})
    return bool(t.get("enabled") and t.get("bot_token") and t.get("chat_id"))


async def send_telegram_message(text: str) -> bool:
    """Envoie un message via le bot Telegram."""
    if not _is_enabled():
        return False
    t = SETTINGS["telegram"]
    url = f"https://api.telegram.org/bot{t['bot_token']}/sendMessage"
    payload = {
        "chat_id": t["chat_id"],
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, timeout=10.0)
            return r.status_code == 200
    except Exception:
        return False


async def alert_trade(
    market: str,
    outcome: str,
    side: str,
    size: float,
    price: float,
    reason: str = "",
) -> None:
    """Alerte pour un trade exécuté."""
    msg = (
        f"<b>NEXUS BET Trade</b>\n"
        f"Market: {market[:50]}...\n"
        f"Outcome: {outcome}\n"
        f"Side: {side} | Size: {size:.4f} @ {price:.2%}\n"
    )
    if reason:
        msg += f"Reason: {reason}\n"
    await send_telegram_message(msg)


async def alert_signal(
    market: str,
    outcome: str,
    edge_pct: float,
    confidence: float,
    debate_summary: str = "",
) -> None:
    """Alerte pour un signal de trading détecté."""
    msg = (
        f"<b>NEXUS BET Signal</b>\n"
        f"Market: {market[:50]}...\n"
        f"Outcome: {outcome}\n"
        f"Edge: {edge_pct:.1f}% | Confidence: {confidence:.0%}\n"
    )
    if debate_summary:
        msg += f"\nDebate: {debate_summary[:200]}...\n"
    await send_telegram_message(msg)


async def alert_error(error: str, context: str = "") -> None:
    """Alerte pour une erreur critique."""
    msg = f"<b>NEXUS BET Error</b>\n{error}\n"
    if context:
        msg += f"Context: {context}\n"
    await send_telegram_message(msg)


async def alert_startup() -> None:
    """Alerte au démarrage du bot."""
    await send_telegram_message("NEXUS BET bot started.")
