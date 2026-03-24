"""
NEXUS BET - Push alerts : envoie les alertes sniper à tous les abonnés actifs.
Broadcast instantané sur Telegram avec boutons SNIPE / PASS.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
from typing import Any

import httpx

log = logging.getLogger("nexus.push_alerts")


# ── Helpers Supabase ──────────────────────────────────────────────────────────

async def get_active_subscribers() -> list[dict[str, Any]]:
    """Retourne les utilisateurs actifs (is_active=true) depuis Supabase."""
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        log.warning("push_alerts: Supabase non configuré")
        return []
    try:
        async with httpx.AsyncClient(timeout=6.0) as c:
            r = await c.get(
                f"{url}/rest/v1/users",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                params={"is_active": "eq.true", "select": "telegram_chat_id"},
            )
            if r.status_code != 200:
                log.warning("push_alerts: Supabase status %d", r.status_code)
                return []
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception as e:
        log.error("get_active_subscribers: %s", e)
        return []


# ── Kelly simplifié pour le bouton ───────────────────────────────────────────

def calculate_kelly(signal) -> float:
    """Calcule le montant Kelly suggéré pour un signal sniper."""
    try:
        from config.settings import settings as _s
        cap = getattr(_s, "POLYMARKET_CAPITAL_USD", 1000.0)
        # Kelly fraction = confidence × 10% du capital (conservateur)
        return round(max(1.0, cap * signal.confidence * 0.10), 0)
    except Exception:
        return 10.0


# ── Push broadcast ────────────────────────────────────────────────────────────

async def push_sniper_alert(signal) -> None:
    """
    Envoie l'alerte sniper à tous les abonnés actifs simultanément.
    `signal` est un SniperSignal de core.sniper.
    """
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        log.warning("push_sniper_alert: TELEGRAM_BOT_TOKEN manquant")
        return

    users = await get_active_subscribers()
    if not users:
        log.debug("push_sniper_alert: aucun abonné actif")
        return

    kelly_usd = calculate_kelly(signal)
    target_pct = (signal.target_price / signal.price - 1) * 100
    stop_pct   = (1 - signal.stop_price / signal.price) * 100
    safe_question = html.escape(signal.question[:60])
    safe_signals  = " · ".join(html.escape(s) for s in signal.signals)

    L = "━━━━━━━━━━━━━━━"
    message = (
        f"⚡ <b>SNIPER ALERT</b>\n{L}\n"
        f"<b>{safe_question}</b>\n\n"
        f"<code>"
        f"PRIX    {signal.price:.3f}\n"
        f"TARGET  {signal.target_price:.3f} (+{target_pct:.0f}%)\n"
        f"STOP    {signal.stop_price:.3f} (-{stop_pct:.0f}%)\n"
        f"CONF    {signal.confidence * 100:.0f}%"
        f"</code>\n{L}\n"
        f"🔍 {safe_signals}"
    )

    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"⚡ SNIPE ${kelly_usd:.0f}",
            callback_data=f"snipe_{signal.market_id}",
        ),
        InlineKeyboardButton(
            "❌ PASS",
            callback_data=f"pass_{signal.market_id}",
        ),
    ]])

    bot = Bot(token=token)
    tasks = []
    for user in users:
        chat_id = user.get("telegram_chat_id")
        if not chat_id:
            continue
        tasks.append(
            _send_safe(bot, chat_id, message, buttons)
        )

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if r is True)
        log.info(
            "push_sniper_alert: sent to %d/%d subscribers | signals=%s",
            ok, len(tasks), signal.signals,
        )
    await bot.close()


async def _send_safe(bot, chat_id: str, text: str, markup) -> bool:
    """Envoie un message sans lever d'exception (utilisateur bloqué, etc.)."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML",
        )
        return True
    except Exception as e:
        log.debug("_send_safe(%s): %s", chat_id, e)
        return False
