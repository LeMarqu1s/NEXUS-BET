"""
NEXUS BET - Alertes Telegram
Notifications pour trades, erreurs et signaux.
"""
import logging
from typing import Optional

import httpx

from config.settings import SETTINGS

log = logging.getLogger(__name__)


def _is_enabled() -> bool:
    t = SETTINGS.get("telegram")
    if not t:
        return False
    token = getattr(t, "bot_token", None) or ""
    chat_id = getattr(t, "chat_id", None) or ""
    enabled = getattr(t, "enabled", False)
    return bool(enabled and token and chat_id)


async def send_telegram_message(text: str, chat_id: Optional[str] = None) -> bool:
    """Envoie un message via le bot Telegram."""
    if not _is_enabled():
        log.debug("Telegram disabled or not configured")
        return False
    t = SETTINGS["telegram"]
    token = getattr(t, "bot_token", None)
    cid = chat_id or getattr(t, "chat_id", None)
    if not token or not cid:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, json=payload)
            if r.status_code != 200:
                log.warning("Telegram API error: %s %s", r.status_code, r.text[:200])
                return False
            return True
    except Exception as e:
        log.warning("Telegram send failed: %s", e)
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


async def alert_startup() -> bool:
    """Alerte au démarrage du bot. Retourne True si envoyé."""
    msg = (
        "<b>NEXUS BET</b> bot started.\n"
        "Commands: /start /scan /debrief /portfolio /agents /btc /fomc"
    )
    return await send_telegram_message(msg)
