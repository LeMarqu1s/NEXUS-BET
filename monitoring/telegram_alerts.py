"""
NEXUS BET - Alertes Telegram
Notifications pour trades, erreurs et signaux.
"""
import logging
from typing import Optional

import httpx

from config.settings import SETTINGS, settings

log = logging.getLogger(__name__)


def _is_enabled() -> bool:
    t = SETTINGS.get("telegram")
    if not t:
        return False
    token = getattr(t, "bot_token", None) or ""
    chat_id = getattr(t, "chat_id", None) or ""
    enabled = getattr(t, "enabled", False)
    return bool(enabled and token and chat_id)


async def send_telegram_message(
    text: str,
    chat_id: Optional[str] = None,
    reply_markup: Optional[dict] = None,
) -> bool:
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
    if reply_markup:
        payload["reply_markup"] = reply_markup
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


def _signal_inline_keyboard(market_id: str, side: str) -> dict:
    """Boutons [Investiguer] [Forcer l'achat] [Ignorer] pour une alerte."""
    cb_prefix = f"{market_id[:40]}|{side}"
    return {
        "inline_keyboard": [
            [
                {"text": "🔍 Investiguer", "callback_data": f"inv_{cb_prefix}"},
                {"text": "💰 Forcer l'achat", "callback_data": f"buy_{cb_prefix}"},
                {"text": "⏭ Ignorer", "callback_data": f"ignore_{cb_prefix}"},
            ]
        ]
    }


async def alert_signal(
    market: str,
    outcome: str,
    edge_pct: float,
    confidence: float,
    debate_summary: str = "",
    kelly_pct: float = 0.0,
    question: str = "",
) -> None:
    """Alerte premium pour un signal de trading détecté (format 🟢 Opportunité | 📊 Edge | 💰 Kelly %)."""
    msg = (
        f"🟢 <b>OPPORTUNITÉ</b>\n\n"
        f"📊 <b>Edge:</b> {edge_pct:.2f}%\n"
        f"💰 <b>Kelly:</b> {kelly_pct:.2f}%\n"
        f"📈 <b>Side:</b> {outcome} | Confiance: {confidence:.0f}%\n\n"
        f"<i>{question[:80] or market[:50]}...</i>"
    )
    if debate_summary:
        msg += f"\n\n💬 {debate_summary[:150]}..."
    await send_telegram_message(msg, reply_markup=_signal_inline_keyboard(market, outcome))


async def alert_error(error: str, context: str = "") -> None:
    """Alerte pour une erreur critique."""
    msg = f"<b>NEXUS BET Error</b>\n{error}\n"
    if context:
        msg += f"Context: {context}\n"
    await send_telegram_message(msg)


async def alert_startup() -> bool:
    """Message au démarrage — NEXUS CAPITAL ONLINE."""
    import os
    n_assets = 0
    capital = getattr(settings, "POLYMARKET_CAPITAL_USD", 0) or 0
    gamma_url = "https://gamma-api.polymarket.com"
    try:
        pm = SETTINGS.get("polymarket")
        if pm:
            gamma_url = getattr(pm, "gamma_url", gamma_url)
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{gamma_url}/markets",
                params={"limit": 100, "active": "true", "closed": "false", "archived": "false"},
            )
            if r.status_code == 200:
                data = r.json()
                markets = data if isinstance(data, list) else data.get("data", []) or []
                n_assets = len(markets)
    except Exception:
        pass
    sim = os.getenv("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")
    mode = "SIMULATION" if sim else "LIVE"
    msg = (
        "⚡ <b>NEXUS CAPITAL</b> — ONLINE\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 Scanner     {n_assets} assets actifs\n"
        f"🔄 Mode        {mode}\n"
        f"💰 Capital     ${capital:,.2f} USDC\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "/start pour accéder au terminal"
    )
    return await send_telegram_message(msg)


async def send_wealth_suggestion(
    balance_usdc: float,
    market_id: str,
    question: str,
    outcome: str,
    side: str,
    pct_yes: float,
    profile: str,
    suggested_amount: float,
    limit_price: float,
) -> bool:
    """
    Envoie la suggestion CEO style Robo-Advisor prédictif.
    Boutons [✅ Approuver] [❌ Attendre] → exécution <500ms.
    """
    from monitoring.wealth_suggestions import store_suggestion

    sid = store_suggestion(
        market_id=market_id,
        outcome=outcome,
        side=side,
        size_usd=suggested_amount,
        limit_price=limit_price,
        question=question,
        pct_yes=pct_yes,
        profile=profile,
    )
    profile_label = {
        "conservateur": "🛡️ Conservateur",
        "quantitatif": "📊 Quantitatif",
        "degen": "🔥 Degen",
    }.get(profile, profile)
    msg = (
        f"<b>CEO</b>, ton solde actuel est de <b>{balance_usdc:,.2f} USDC</b>.\n\n"
        f"Le Swarm est à <b>{pct_yes:.0f}%</b> sur le marché « {question[:50]}... »\n\n"
        f"Vu ton profil <b>{profile_label}</b>, je suggère de placer <b>{suggested_amount:.2f}$</b>.\n\n"
        f"<i>YES @ {limit_price:.2f} | Edge validé par 20 agents</i>"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Approuver", "callback_data": f"approve_{sid}"},
                {"text": "❌ Attendre", "callback_data": f"wait_{sid}"},
            ]
        ]
    }
    return await send_telegram_message(msg, reply_markup=reply_markup)


async def send_alpha_stream(agent_name: str, analysis: str, market_context: str = "") -> bool:
    """
    Flux Alpha : analyses des agents Paperclip (style Twitter/X).
    Interface ultra-premium pour le flux d'alpha.
    """
    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        f"📡 <b>ALPHA STREAM</b>",
        f"<b>{agent_name}</b>",
        "",
        analysis[:600],
    ]
    if market_context:
        lines.append(f"\n<i>Context: {market_context[:100]}...</i>")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    msg = "\n".join(lines)
    return await send_telegram_message(msg)


async def send_photo_bytes(photo_bytes: bytes, caption: str = "", chat_id: str | None = None) -> bool:
    """Send PNG image bytes via Telegram send_photo API."""
    if not _is_enabled():
        return False
    t = SETTINGS["telegram"]
    token = getattr(t, "bot_token", None)
    cid = chat_id or getattr(t, "chat_id", None)
    if not token or not cid:
        return False
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                url,
                data={"chat_id": cid, "caption": caption[:1024], "parse_mode": "HTML"},
                files={"photo": ("signal_card.png", photo_bytes, "image/png")},
            )
            if r.status_code != 200:
                log.warning("send_photo failed: %s %s", r.status_code, r.text[:200])
                return False
            return True
    except Exception as e:
        log.warning("send_photo error: %s", e)
        return False


async def send_signal_card(signal: dict, chat_id: str | None = None) -> bool:
    """
    Generate and send a premium signal card image via Telegram.
    Falls back to text message if image generation fails.
    """
    try:
        from monitoring.signal_card_generator import generate_signal_card_safe
        png = generate_signal_card_safe(signal)
        if png:
            q = (signal.get("question") or signal.get("market_id", "?"))[:80]
            edge = float(signal.get("edge_pct", 0))
            strength = signal.get("signal_strength", "BUY")
            icon = "⚡" if strength == "STRONG_BUY" else "▲"
            caption = (
                f"{icon} <b>{strength}</b>\n"
                f"<i>{q}</i>\n"
                f"Edge: <b>{edge:.1f}%</b>"
            )
            return await send_photo_bytes(png, caption, chat_id)
    except Exception as e:
        log.warning("send_signal_card failed: %s", e)
    # Fallback to text
    edge = float(signal.get("edge_pct", 0))
    q = (signal.get("question") or "")[:60]
    rec = signal.get("recommended_outcome") or signal.get("side", "?")
    msg = f"⚡ <b>SIGNAL DÉTECTÉ</b>\n{q}\n{rec} | Edge: {edge:.1f}%"
    return await send_telegram_message(msg, chat_id)


async def alert_anti_sybil(details: str) -> bool:
    """Alerte manipulation : Mirror Trading détecté par Whale Tracker."""
    msg = (
        "🚨 <b>ALERTE MANIPULATION</b>\n\n"
        "Le Whale Tracker a détecté du Mirror Trading sur une baleine cible.\n\n"
        f"<i>{details[:300]}</i>"
    )
    return await send_telegram_message(msg)
