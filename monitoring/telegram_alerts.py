"""
NEXUS BET - Alertes Telegram
Notifications pour trades, erreurs et signaux.
"""
import logging
import os
from typing import Optional

import httpx

from config.settings import SETTINGS, settings

log = logging.getLogger(__name__)


async def send_photo_to_chat(
    chat_id: str,
    photo_bytes: bytes,
    caption: str = "",
    reply_markup: Optional[dict] = None,
    token: Optional[str] = None,
) -> bool:
    """Envoie une photo via l'API Telegram (multipart/form-data)."""
    _token = token or (
        (SETTINGS.get("telegram") and getattr(SETTINGS["telegram"], "bot_token", None))
        or os.getenv("TELEGRAM_BOT_TOKEN")
        or os.getenv("TELEGRAM_TOKEN")
    )
    if not _token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{_token}/sendPhoto"
    data = {
        "chat_id": chat_id,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    if caption:
        data["caption"] = caption
    if reply_markup:
        import json as _json
        data["reply_markup"] = _json.dumps(reply_markup)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            files = {"photo": ("signal_card.png", photo_bytes, "image/png")}
            r = await client.post(url, data=data, files=files)
            return r.status_code == 200
    except Exception as e:
        log.debug("send_photo_to_chat %s: %s", chat_id, e)
        return False


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
    line = "━━━━━━━━━━━━━━━"
    msg = (
        f"<b>✅ TRADE EXÉCUTÉ</b>\n{line}\n"
        f"<code>MARCHÉ  {market[:40]}\n"
        f"SIDE    {outcome} {side}\n"
        f"SIZE    {size:.4f} @ {price:.2%}"
    )
    if reason:
        msg += f"\nRAISON  {reason[:30]}"
    msg += f"</code>\n{line}"
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
    line = "━━━━━━━━━━━━━━━"
    cat = _detect_category(question or market)
    conf_str = _conf_label(confidence / 100 if confidence > 1 else confidence)
    q_str = (question or market)[:72]
    msg = (
        f"<b>⚡ SIGNAL · {cat}</b>\n{line}\n"
        f"<b>{q_str}</b>\n"
        f"<code>EDGE    {edge_pct:.1f}%\n"
        f"KELLY   {kelly_pct:.1f}%\n"
        f"SIDE    {outcome}\n"
        f"CONF    {conf_str}</code>\n"
        f"{line}"
    )
    if debate_summary:
        msg += f"\n<i>{debate_summary[:120]}</i>"
    await send_telegram_message(msg, reply_markup=_signal_inline_keyboard(market, outcome))


async def alert_error(error: str, context: str = "") -> None:
    line = "━━━━━━━━━━━━━━━"
    msg = f"<b>⚠️ ERREUR SYSTÈME</b>\n{line}\n<code>{error[:200]}"
    if context:
        msg += f"\n{context[:100]}"
    msg += f"</code>\n{line}"
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
    mode = "SIM" if sim else "LIVE"
    dot = "🔵" if sim else "🟢"
    line = "━━━━━━━━━━━━━━━"
    msg = (
        f"<b>⚡ NEXUS BET — ONLINE</b>\n{line}\n"
        f"<code>SCANNER  {n_assets} marchés actifs\n"
        f"MODE     {mode}\n"
        f"CAPITAL  ${capital:,.2f} USDC</code>\n"
        f"{line}\n"
        f"{dot} <i>Tape /start pour accéder au terminal.</i>"
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


async def alert_anti_sybil(details: str) -> bool:
    """Alerte manipulation : Mirror Trading détecté par Whale Tracker."""
    msg = (
        "🚨 <b>ALERTE MANIPULATION</b>\n\n"
        "Le Whale Tracker a détecté du Mirror Trading sur une baleine cible.\n\n"
        f"<i>{details[:300]}</i>"
    )
    return await send_telegram_message(msg)


async def _get_active_subscriber_chat_ids() -> list[str]:
    """Retourne les telegram_chat_id de tous les abonnés actifs (Supabase)."""
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if url and key:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{url}/rest/v1/users",
                    params={
                        "is_active": "eq.true",
                        "select": "telegram_chat_id",
                    },
                    headers={"apikey": key, "Authorization": f"Bearer {key}"},
                )
                if r.status_code == 200:
                    rows = r.json()
                    ids = [row["telegram_chat_id"] for row in rows if row.get("telegram_chat_id")]
                    if ids:
                        return ids
        except Exception as e:
            log.debug("_get_active_subscriber_chat_ids: %s", e)
    # Fallback: env var TELEGRAM_CHAT_ID
    cid = os.getenv("TELEGRAM_CHAT_ID", "")
    return [cid] if cid else []


def _signal_buy_keyboard(market_id: str, side: str) -> dict:
    """Boutons [✅ BUY] [❌ PASS] pour le signal pushé aux abonnés."""
    cb = f"{market_id[:40]}|{side}"
    return {
        "inline_keyboard": [
            [
                {"text": "✅ BUY", "callback_data": f"buy_{cb}"},
                {"text": "❌ PASS", "callback_data": f"ignore_{cb}"},
            ]
        ]
    }


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


async def push_signal_to_subscribers(
    market_id: str,
    question: str,
    side: str,
    edge_pct: float,
    confidence: float,
    kelly_fraction: float,
    polymarket_price: float,
    signal_strength: str = "BUY",
    capital: float = 1000.0,
) -> int:
    """
    Push signal premium à tous les abonnés actifs.
    Format : titre en gras, code block pour les métriques, boutons CONFIRMER/IGNORER.
    Returns nombre d'envois réussis.
    """
    chat_ids = await _get_active_subscriber_chat_ids()
    if not chat_ids:
        return 0

    t = SETTINGS.get("telegram")
    token = getattr(t, "bot_token", None) if t else None
    token = token or os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        return 0

    # Métriques
    stake = round(capital * min(kelly_fraction, 0.05), 2)
    ev = round(edge_pct * confidence, 1)
    cat = _detect_category(question)
    strength_label = "STRONG BUY" if signal_strength == "STRONG_BUY" else "BUY"
    fair_price = round(polymarket_price + (edge_pct / 100), 2)
    poly_pct = round(polymarket_price * 100)
    fair_pct = round(fair_price * 100)
    conf_str = _conf_label(confidence)
    line = "━━━━━━━━━━━━━━━"

    msg = (
        f"<b>⚡ {strength_label} · {cat}</b>\n"
        f"{line}\n"
        f"<b>{question[:72]}</b>\n"
        f"<code>EV      +{ev:.1f}%\n"
        f"EDGE    {edge_pct:.1f}pts\n"
        f"MISE    ${stake:.2f}\n"
        f"CONF    {conf_str}</code>\n"
        f"{line}\n"
        f"<i>POLY: {poly_pct}% · FAIR: {fair_pct}% · NEXUS BET</i>"
    )

    kb = {
        "inline_keyboard": [
            [
                {"text": "✅ CONFIRMER", "callback_data": f"buy_{market_id[:40]}|{side}"},
                {"text": "✕ IGNORER",   "callback_data": f"ignore_{market_id[:40]}|{side}"},
            ]
        ]
    }

    # Try to generate signal card image
    card_bytes: Optional[bytes] = None
    try:
        from monitoring.signal_card import generate_signal_card
        card_bytes = generate_signal_card(
            question=question,
            signal_strength=signal_strength,
            category=cat,
            edge_pct=edge_pct,
            ev_pct=ev,
            kelly_fraction=kelly_fraction,
            polymarket_price=polymarket_price,
            fair_price=fair_price,
            confidence=confidence,
            capital=capital,
            side=side,
        )
    except Exception as _e:
        log.debug("signal_card generation failed: %s", _e)

    sent = 0
    for chat_id in chat_ids:
        try:
            ok = False
            # Try photo first if card available
            if card_bytes:
                ok = await send_photo_to_chat(
                    chat_id=chat_id,
                    photo_bytes=card_bytes,
                    caption=msg,
                    reply_markup=kb,
                    token=token,
                )
            # Fallback to text message
            if not ok:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": msg,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True,
                            "reply_markup": kb,
                        },
                    )
                    ok = r.status_code == 200
                    if not ok:
                        log.debug("push_signal to %s: %s %s", chat_id, r.status_code, r.text[:80])
            if ok:
                sent += 1
        except Exception as e:
            log.debug("push_signal to %s failed: %s", chat_id, e)

    log.info("push_signal_to_subscribers: sent to %d/%d subscribers", sent, len(chat_ids))
    return sent
