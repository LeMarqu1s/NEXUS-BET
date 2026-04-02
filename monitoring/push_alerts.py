"""
NEXUS BET - Push alerts : envoie les alertes sniper à tous les abonnés actifs.
Broadcast instantané sur Telegram avec boutons SNIPE / PASS.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import time
from typing import Any

import httpx

log = logging.getLogger("nexus.push_alerts")

# ── Flood control persistant (survit aux redémarrages) ────────────────────────
_FLOOD_FILE = "/tmp/tg_flood_until.txt"
_flood_until: float = 0.0

def _load_flood_until() -> float:
    try:
        with open(_FLOOD_FILE) as f:
            return float(f.read().strip())
    except Exception:
        return 0.0

def _save_flood_until(ts: float) -> None:
    try:
        with open(_FLOOD_FILE, "w") as f:
            f.write(str(ts))
    except Exception:
        pass

_flood_until = _load_flood_until()  # charge au démarrage du module


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
    # Fallback : si Supabase vide ou non configuré → toujours alerter TELEGRAM_CHAT_ID
    fallback_id = os.getenv("TELEGRAM_CHAT_ID")
    if not users:
        if fallback_id:
            log.info("push_sniper_alert: no subscribers in DB — using TELEGRAM_CHAT_ID fallback")
            users = [{"telegram_chat_id": fallback_id}]
        else:
            log.warning("push_sniper_alert: no subscribers and TELEGRAM_CHAT_ID not set — alert dropped")
            return
    log.info("push_sniper_alert: sending to %d subscriber(s) | signals=%s", len(users), signal.signals)

    kelly_usd = calculate_kelly(signal)
    target_pct = (signal.target_price / signal.price - 1) * 100
    stop_pct   = (1 - signal.stop_price / signal.price) * 100
    safe_question = html.escape(signal.question[:60])
    n_triggers = len(signal.signals)
    safe_signals  = " + ".join(html.escape(s) for s in signal.signals)
    conf_pct = int(signal.confidence * 100)
    conf_icon = "🔥" if conf_pct >= 80 else "✅" if conf_pct >= 60 else "⚠️"
    confluence_bar = "█" * n_triggers + "░" * (4 - n_triggers)

    # Category emoji
    q_lower = signal.question.lower()
    if any(k in q_lower for k in ("nba", "ncaa", "basketball")):
        cat_e = "🏀"
    elif any(k in q_lower for k in ("soccer", "football", "fifa")):
        cat_e = "⚽"
    elif any(k in q_lower for k in ("tennis")):
        cat_e = "🎾"
    elif any(k in q_lower for k in ("trump", "election", "president")):
        cat_e = "🇺🇸"
    elif any(k in q_lower for k in ("btc", "bitcoin", "eth", "crypto")):
        cat_e = "₿"
    elif any(k in q_lower for k in ("oil", "crude")):
        cat_e = "🛢️"
    else:
        cat_e = "📊"

    L = "━━━━━━━━━━━━━━━"
    message = (
        f"⚡ <b>SNIPER SIGNAL</b> {cat_e}\n{L}\n"
        f"🎯 Confluence: <b>{n_triggers}/4</b> [{confluence_bar}]\n"
        f"📊 {safe_signals}\n\n"
        f"<b>{safe_question}</b>\n\n"
        f"<code>"
        f"PRIX    {signal.price:.3f}\n"
        f"TARGET  {signal.target_price:.3f} (+{target_pct:.0f}%)\n"
        f"STOP    {signal.stop_price:.3f} (-{stop_pct:.0f}%)\n"
        f"CONF    {conf_pct}% {conf_icon}"
        f"</code>\n{L}\n"
        f"⚠️ <i>Pas un conseil en investissement.</i>"
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
    try:
        await bot.close()
    except Exception:
        pass


async def push_auto_snipe_notification(signal, order_id: str | None) -> None:
    """
    Notification post-exécution quand AUTO_SNIPE=true.
    Différente de push_sniper_alert : indique que l'ordre est déjà placé.
    """
    from telegram import Bot

    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        return
    users = await get_active_subscribers()
    fallback_id = os.getenv("TELEGRAM_CHAT_ID")
    if not users and fallback_id:
        users = [{"telegram_chat_id": fallback_id}]
    if not users:
        return

    safe_question = html.escape(signal.question[:60])
    status = f"✅ ORDER <code>{html.escape(str(order_id))}</code>" if order_id else "❌ ÉCHEC ORDRE"
    L = "━━━━━━━━━━━━━━━"
    message = (
        f"⚡ <b>SNIPE EXÉCUTÉ</b>\n{L}\n"
        f"<b>{safe_question}</b>\n\n"
        f"<code>"
        f"PRIX    {signal.price:.3f}\n"
        f"TARGET  {signal.target_price:.3f} (+{(signal.target_price/signal.price-1)*100:.0f}%)\n"
        f"STOP    {signal.stop_price:.3f} (-{(1-signal.stop_price/signal.price)*100:.0f}%)"
        f"</code>\n{L}\n"
        f"{status}"
    )

    bot = Bot(token=token)
    tasks = [_send_safe(bot, u.get("telegram_chat_id", ""), message, None)
             for u in users if u.get("telegram_chat_id")]
    await asyncio.gather(*tasks, return_exceptions=True)
    try:
        await bot.close()
    except Exception:
        pass


async def _send_safe(bot, chat_id: str, text: str, markup) -> bool:
    """Envoie un message sans lever d'exception (utilisateur bloqué, etc.)."""
    global _flood_until
    if time.time() < _flood_until:
        remaining = int(_flood_until - time.time())
        log.warning("_send_safe: flood control actif encore %ds — message ignoré", remaining)
        return False
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML",
        )
        return True
    except Exception as e:
        err = str(e)
        if "Flood control" in err or "retry after" in err.lower():
            import re
            m = re.search(r"(\d+)", err)
            retry_secs = int(m.group(1)) if m else 60
            _flood_until = time.time() + retry_secs
            _save_flood_until(_flood_until)
            log.warning("_send_safe: flood control Telegram — pause %ds (persisté)", retry_secs)
        else:
            log.warning("_send_safe(%s): %s", chat_id, e)
        return False


# ── Permission model (confirmation trade > 10 USDC en live) ──────────────────

_confirm_futures: dict[str, "asyncio.Future[bool]"] = {}


async def push_confirm_request(signal, size_usd: float, chat_ids: list[str]) -> bool:
    """Envoie un bouton Confirmer/Annuler et attend 60s la réponse."""
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token or not chat_ids:
        return False
    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()
    _confirm_futures[signal.market_id] = fut
    safe_q = html.escape(signal.question[:60])
    text = (
        f"🔐 <b>CONFIRMATION REQUISE</b>\n━━━━━━━━━━━━━━━\n"
        f"<b>{safe_q}</b>\n\n"
        f"<code>MONTANT  ${size_usd:.0f} USDC\n"
        f"PRIX     {signal.price:.3f}\n"
        f"TARGET   {signal.target_price:.3f}\n"
        f"STOP     {signal.stop_price:.3f}</code>\n"
        f"━━━━━━━━━━━━━━━\n⏱️ <i>Auto-annulation dans 60s</i>"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmer", callback_data=f"confirm_snipe_{signal.market_id}"),
        InlineKeyboardButton("❌ Annuler",   callback_data=f"cancel_snipe_{signal.market_id}"),
    ]])
    bot = Bot(token=token)
    try:
        await asyncio.gather(
            *[_send_safe(bot, cid, text, kb) for cid in chat_ids],
            return_exceptions=True,
        )
    finally:
        try:
            await bot.close()
        except Exception:
            pass
    try:
        return await asyncio.wait_for(asyncio.shield(fut), timeout=60.0)
    except asyncio.TimeoutError:
        log.info("Confirmation timeout pour %s — annulé", signal.market_id[:16])
        return False
    finally:
        _confirm_futures.pop(signal.market_id, None)


def resolve_confirm(market_id: str, confirmed: bool) -> None:
    """Résout la confirmation depuis le callback Telegram."""
    fut = _confirm_futures.get(market_id)
    if fut and not fut.done():
        fut.set_result(confirmed)


# ── Scalp alerts ──────────────────────────────────────────────────────────────

async def push_scalp_signal(signal) -> None:
    """Alerte Telegram enrichie pour un marché 'Up or Down' < 30min."""
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        return

    users = await get_active_subscribers()
    fallback_id = os.getenv("TELEGRAM_CHAT_ID")
    if not users:
        if fallback_id:
            users = [{"telegram_chat_id": fallback_id}]
        else:
            return

    sim_mode = os.getenv("SIMULATION_MODE", "true").lower() != "false"
    sim_tag  = " <b>[SIM]</b>" if sim_mode else ""
    safe_q   = html.escape(signal.question[:60])
    yes_pct  = int(signal.yes_price * 100)
    no_pct   = int(signal.no_price  * 100)
    mins     = signal.minutes_remaining
    L = "━━━━━━━━━━━━━━━"

    text = (
        f"🔪 <b>SCALP SIGNAL</b>{sim_tag}\n{L}\n"
        f"<b>{safe_q}</b>\n\n"
        f"<code>"
        f"YES   {yes_pct}¢\n"
        f"NO    {no_pct}¢\n"
        f"TEMPS {mins:.0f} min restantes"
        f"</code>\n{L}\n"
        f"⚠️ <i>Pas un conseil en investissement.</i>"
    )
    # callback_data limité à 64 octets par Telegram — on tronque les IDs
    mid_short = signal.market_id[-20:]
    yes_short = signal.token_id_yes[-20:]
    no_short  = signal.token_id_no[-20:]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✅ BUY YES {yes_pct}¢", callback_data=f"sy_{mid_short}|{yes_short}"),
        InlineKeyboardButton(f"✅ BUY NO {no_pct}¢",  callback_data=f"sn_{mid_short}|{no_short}"),
    ]])

    bot = Bot(token=token)
    tasks = [_send_safe(bot, u["telegram_chat_id"], text, kb)
             for u in users if u.get("telegram_chat_id")]
    if tasks:
        log.info("push_scalp_signal: envoi à %d destinataire(s) — %s", len(tasks), signal.question[:40])
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if r is True)
        log.info("push_scalp_signal: %d/%d envoyés avec succès", ok, len(tasks))
    else:
        log.warning("push_scalp_signal: aucun destinataire trouvé")
    try:
        await bot.close()
    except Exception:
        pass


async def push_scalp_executed(signal, direction: str, entry: float, order_id: str, cfg: dict) -> None:
    """Notification d'un trade scalp auto-exécuté (pas de boutons — info uniquement)."""
    from telegram import Bot
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        return
    users = await get_active_subscribers()
    fallback_id = os.getenv("TELEGRAM_CHAT_ID")
    if not users:
        if fallback_id:
            users = [{"telegram_chat_id": fallback_id}]
        else:
            return

    sim_tag = " <b>[SIM]</b>" if os.getenv("SIMULATION_MODE", "true").lower() != "false" else ""
    tp_price = round(entry * (1 + cfg.get("tp", 0.40)), 3)
    sl_price = round(entry * (1 - cfg.get("sl", 0.25)), 3)
    size_usd = cfg.get("size_usd", 25.0)
    icon = "🟢" if direction == "YES" else "🔴"
    L = "━━━━━━━━━━━━━━━"
    safe_q = html.escape(signal.question[:60])
    text = (
        f"🔪 <b>SCALP AUTO-EXÉCUTÉ</b>{sim_tag}\n{L}\n"
        f"<b>{safe_q}</b>\n\n"
        f"<code>"
        f"{icon} {direction}  @ {entry:.2f}\n"
        f"TP       {tp_price:.2f}  (+{cfg.get('tp',0.40)*100:.0f}%)\n"
        f"SL       {sl_price:.2f}  (-{cfg.get('sl',0.25)*100:.0f}%)\n"
        f"TAILLE   ${size_usd:.0f} USDC"
        f"</code>\n{L}"
    )
    bot = Bot(token=token)
    tasks = [_send_safe(bot, u["telegram_chat_id"], text, None)
             for u in users if u.get("telegram_chat_id")]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    try:
        await bot.close()
    except Exception:
        pass


async def push_scalp_tp_alert(pos, current_price: float, pnl_pct: float) -> None:
    """Alerte TP atteint avec bouton SELL."""
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token or not pos.chat_ids:
        return
    safe_q = html.escape(pos.question[:60])
    L = "━━━━━━━━━━━━━━━"
    text = (
        f"🎯 <b>SCALP TP ATTEINT</b>\n{L}\n"
        f"<b>{safe_q}</b>\n\n"
        f"<code>"
        f"SIDE    {pos.side}\n"
        f"ENTRÉE  {pos.entry_price:.3f}\n"
        f"ACTUEL  {current_price:.3f}\n"
        f"P&L     {pnl_pct:+.1f}%"
        f"</code>\n{L}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("💰 SELL", callback_data=f"scalp_sell_{pos.token_id}"),
    ]])
    bot = Bot(token=token)
    tasks = [_send_safe(bot, cid, text, kb) for cid in pos.chat_ids]
    await asyncio.gather(*tasks, return_exceptions=True)
    try:
        await bot.close()
    except Exception:
        pass


async def push_scalp_sl_alert(pos, current_price: float, pnl_pct: float) -> None:
    """Alerte SL atteint avec bouton SELL."""
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token or not pos.chat_ids:
        return
    safe_q = html.escape(pos.question[:60])
    L = "━━━━━━━━━━━━━━━"
    text = (
        f"🛑 <b>SCALP SL ATTEINT</b>\n{L}\n"
        f"<b>{safe_q}</b>\n\n"
        f"<code>"
        f"SIDE    {pos.side}\n"
        f"ENTRÉE  {pos.entry_price:.3f}\n"
        f"ACTUEL  {current_price:.3f}\n"
        f"P&L     {pnl_pct:+.1f}%"
        f"</code>\n{L}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔴 SELL (stop loss)", callback_data=f"scalp_sell_{pos.token_id}"),
    ]])
    bot = Bot(token=token)
    tasks = [_send_safe(bot, cid, text, kb) for cid in pos.chat_ids]
    await asyncio.gather(*tasks, return_exceptions=True)
    try:
        await bot.close()
    except Exception:
        pass


async def push_sniper_position_update(
    token_id: str, entry: float, current: float, pnl_pct: float, reason: str
) -> None:
    """Notification TP/SL d'une position sniper active."""
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        return
    users = await get_active_subscribers()
    fallback_id = os.getenv("TELEGRAM_CHAT_ID")
    if not users:
        if fallback_id:
            users = [{"telegram_chat_id": fallback_id}]
        else:
            return
    sim_tag = " [SIM]" if os.getenv("SIMULATION_MODE", "true").lower() != "false" else ""
    icon = "🎯" if reason == "TP" else "🛑"
    L = "━━━━━━━━━━━━━━━"
    text = (
        f"{icon} <b>SNIPE {reason}</b>{sim_tag}\n{L}\n"
        f"<code>"
        f"TOKEN  {token_id[:16]}...\n"
        f"ENTRÉE {entry:.4f}\n"
        f"ACTUEL {current:.4f}\n"
        f"P&L    {pnl_pct:+.1f}%"
        f"</code>\n{L}"
    )
    from telegram import Bot
    bot = Bot(token=token)
    tasks = [_send_safe(bot, u["telegram_chat_id"], text, None)
             for u in users if u.get("telegram_chat_id")]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    try:
        await bot.close()
    except Exception:
        pass
