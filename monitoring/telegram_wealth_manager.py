"""
NEXUS CAPITAL - Telegram Wealth Manager (Phase 6)
État du profil de risque, Ladder Mode, Kelly dynamique.
Paperclip Advisor : adaptation à la personnalité du CEO.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("nexus.wealth_manager")

WEALTH_STATE_PATH = Path(__file__).resolve().parent.parent / "telegram_wealth_state.json"

# Profils de risque → Kelly % du capital par trade
RISK_PROFILES = {
    "conservateur": {"kelly_pct": 0.01, "label": "🛡️ Conservateur", "desc": "1% du capital par trade"},
    "quantitatif": {"kelly_pct": 0.025, "label": "📊 Quantitatif", "desc": "2.5% du capital par trade"},
    "degen": {"kelly_pct": 0.10, "label": "🔥 Degen", "desc": "10% du capital par trade"},
}

DEFAULT_PROFILE = "quantitatif"


def _load_state() -> dict[str, Any]:
    if not WEALTH_STATE_PATH.exists():
        return {}
    try:
        with open(WEALTH_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(data: dict[str, Any]) -> None:
    try:
        WEALTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(WEALTH_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.warning("wealth_manager save error: %s", e)


def get_risk_profile() -> str:
    """Retourne le profil actuel : conservateur | quantitatif | degen."""
    return _load_state().get("risk_profile", DEFAULT_PROFILE)


def set_risk_profile(profile: str) -> bool:
    """Définit le profil de risque. Retourne True si OK."""
    if profile not in RISK_PROFILES:
        return False
    state = _load_state()
    state["risk_profile"] = profile
    state["kelly_pct"] = RISK_PROFILES[profile]["kelly_pct"]
    _save_state(state)
    log.info("Wealth Manager: profil=%s kelly=%.2f%%", profile, state["kelly_pct"] * 100)
    return True


def get_kelly_fraction() -> float:
    """
    Kelly fraction pour le moteur de trading (0.01 à 0.10).
    Utilisé par swarm_orchestrator, order_manager, etc.
    """
    state = _load_state()
    profile = state.get("risk_profile", DEFAULT_PROFILE)
    return RISK_PROFILES.get(profile, RISK_PROFILES[DEFAULT_PROFILE])["kelly_pct"]


def get_auto_trade() -> bool:
    """Auto-Trade : exécution automatique des signaux validés par le Swarm."""
    return _load_state().get("auto_trade", False)


def set_auto_trade(enabled: bool) -> None:
    state = _load_state()
    state["auto_trade"] = enabled
    _save_state(state)
    log.info("Wealth Manager: auto_trade=%s", enabled)


def get_ladder_mode() -> bool:
    """Ladder Mode : 100% réinvestissement des gains (objectif x32 en 5 trades)."""
    return _load_state().get("ladder_mode", False)


def set_ladder_mode(enabled: bool) -> None:
    state = _load_state()
    state["ladder_mode"] = enabled
    _save_state(state)
    log.info("Wealth Manager: ladder_mode=%s", enabled)


def get_profile_label(profile: Optional[str] = None) -> str:
    p = profile or get_risk_profile()
    return RISK_PROFILES.get(p, RISK_PROFILES[DEFAULT_PROFILE])["label"]


def compute_suggested_amount_usd(balance_usdc: float, profile: Optional[str] = None) -> float:
    """
    Calcule le montant suggéré selon le profil et le solde.
    LADDER MODE : si activé et last_trade_profit > 0, utilise 100% des gains.
    """
    if get_ladder_mode():
        state = _load_state()
        last_profit = float(state.get("last_trade_profit", 0))
        if last_profit > 0:
            return round(last_profit, 2)
    kelly = RISK_PROFILES.get(profile or get_risk_profile(), RISK_PROFILES[DEFAULT_PROFILE])["kelly_pct"]
    return round(balance_usdc * kelly, 2)


def set_last_trade_profit(profit_usd: float) -> None:
    """Enregistre le profit du dernier trade (pour Ladder Mode)."""
    state = _load_state()
    state["last_trade_profit"] = profit_usd
    _save_state(state)


def set_anti_sybil_alert(detected: bool, details: str = "") -> None:
    """Marque une alerte manipulation (Mirror Trading détecté)."""
    state = _load_state()
    state["anti_sybil_alert"] = detected
    state["anti_sybil_details"] = details
    _save_state(state)


def get_anti_sybil_alert() -> tuple[bool, str]:
    """Retourne (alert_active, details)."""
    state = _load_state()
    return state.get("anti_sybil_alert", False), state.get("anti_sybil_details", "")


def get_whale_wallets() -> list[str]:
    """Liste des adresses à surveiller (paste & monitor)."""
    return list(_load_state().get("whale_wallets", []) or [])


def add_whale_wallet(address: str) -> bool:
    """Ajoute une adresse à whale_wallets. Retourne True si OK."""
    addr = (address or "").strip()
    if not addr or len(addr) != 42 or not addr.startswith("0x"):
        return False
    state = _load_state()
    wallets = list(state.get("whale_wallets", []) or [])
    if addr.lower() in [w.lower() for w in wallets]:
        return True
    wallets.append(addr)
    state["whale_wallets"] = wallets
    _save_state(state)
    log.info("Wealth: whale wallet added %s", addr[:16])
    return True


def get_copy_trade_enabled() -> bool:
    """Copy Wallet : activé ou non."""
    return _load_state().get("copy_trade_enabled", False)


def set_copy_trade_enabled(enabled: bool) -> None:
    """Toggle Copy Wallet."""
    state = _load_state()
    state["copy_trade_enabled"] = enabled
    _save_state(state)
    log.info("Wealth: copy_trade_enabled=%s", enabled)
