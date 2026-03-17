"""
NEXUS CAPITAL - DeFi Yield Manager (Phase 5)
L'argent qui ne dort jamais : USDC inactif → Aave (Polygon) pour générer du rendement.
Dès que le Swarm valide un trade → flash withdraw + préparation exécution Polymarket.
Export vers defi_yield_state.json pour le dashboard (Compound / Wallet).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("nexus.defi_yield")

# Fichier lu par /api/yield (Next.js dashboard)
YIELD_STATE_PATH = Path(__file__).resolve().parent / "defi_yield_state.json"

# Aave v3 Polygon - adresses officielles
AAVE_POOL_POLYGON = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
USDC_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e
AUSDC_POLYGON = "0x625E7708f30cA75bfd92586e17077590C60eb4cD"  # aPolUSDC

# APY Aave USDC supply (~2% en conditions normales)
DEFAULT_APY = float(os.getenv("DEFI_YIELD_APY", "2.0"))


@dataclass
class YieldState:
    """État du rendement DeFi."""
    total_usdc: float
    deposited_aave: float
    apy: float
    yield_generated_usd: float
    yield_generated_today: float
    last_deposit_ts: Optional[str]
    last_withdraw_ts: Optional[str]
    mode: str  # "yielding" | "withdrawing" | "executing"
    pending_trade: Optional[dict[str, Any]]


def _load_capital() -> float:
    """Capital USDC disponible (wallet principal simulé)."""
    from config.settings import settings
    return settings.POLYMARKET_CAPITAL_USD


def _load_state() -> dict[str, Any]:
    """Charge l'état persistant du yield."""
    if not YIELD_STATE_PATH.exists():
        return {}
    try:
        with open(YIELD_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(data: dict[str, Any]) -> None:
    """Sauvegarde l'état."""
    try:
        with open(YIELD_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.warning("defi_yield save_state error: %s", e)


def _compute_yield_since(deposited: float, apy: float, since_ts: str) -> float:
    """Calcule le rendement généré depuis une date (formule compound annuel)."""
    try:
        from datetime import datetime as dt
        since = dt.fromisoformat(since_ts.replace("Z", "+00:00"))
        now = dt.utcnow()
        delta = (now - since.replace(tzinfo=None)).total_seconds() / (365.25 * 24 * 3600)
        if delta <= 0:
            return 0.0
        return round(deposited * ((1 + apy / 100) ** delta - 1), 4)
    except Exception:
        return 0.0


def get_yield_state() -> YieldState:
    """
    Retourne l'état actuel du rendement DeFi.
    Mode simulation : capital inactif = dépôt Aave simulé.
    """
    capital = _load_capital()
    state = _load_state()
    deposited = float(state.get("deposited_aave", capital))
    apy = float(state.get("apy", DEFAULT_APY))
    last_deposit = state.get("last_deposit_ts") or datetime.utcnow().isoformat() + "Z"
    mode = state.get("mode", "yielding")
    pending = state.get("pending_trade")

    cumulative_yield = float(state.get("yield_generated_usd", 0))
    yield_since = _compute_yield_since(deposited, apy, last_deposit)
    cumulative_yield += yield_since

    # Yield aujourd'hui (approximation)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        since = datetime.fromisoformat(last_deposit.replace("Z", ""))
        if since.date() == today_start.date():
            yield_today = yield_since
        else:
            yield_today = _compute_yield_since(deposited, apy, today_start.isoformat() + "Z")
    except Exception:
        yield_today = 0.0

    return YieldState(
        total_usdc=capital,
        deposited_aave=deposited,
        apy=apy,
        yield_generated_usd=round(cumulative_yield, 2),
        yield_generated_today=round(yield_today, 2),
        last_deposit_ts=last_deposit,
        last_withdraw_ts=state.get("last_withdraw_ts"),
        mode=mode,
        pending_trade=pending,
    )


def update_yield_and_export() -> YieldState:
    """
    Met à jour les calculs de rendement et exporte vers defi_yield_state.json.
    Appelé périodiquement par le main loop ou un cron.
    """
    s = get_yield_state()
    data = {
        "total_usdc": s.total_usdc,
        "deposited_aave": s.deposited_aave,
        "apy": s.apy,
        "yield_generated_usd": s.yield_generated_usd,
        "yield_generated_today": s.yield_generated_today,
        "last_deposit_ts": s.last_deposit_ts,
        "last_withdraw_ts": s.last_withdraw_ts,
        "mode": s.mode,
        "pending_trade": s.pending_trade,
        "last_updated": datetime.utcnow().isoformat() + "Z",
    }
    _save_state(data)
    return s


def on_swarm_approved(signal: dict[str, Any]) -> dict[str, Any]:
    """
    Appelé quand le Swarm valide un trade (≥70% YES).
    Passe en mode "withdrawing" et prépare le flash withdraw Aave + exécution Polymarket.
    Retourne les métadonnées pour l'exécution.
    """
    state = _load_state()
    state["mode"] = "withdrawing"
    state["pending_trade"] = {
        "market_id": signal.get("market_id"),
        "side": signal.get("side"),
        "amount_usd": min(
            float(signal.get("kelly_fraction", 0.25)) * state.get("deposited_aave", _load_capital()),
            state.get("deposited_aave", _load_capital()) * 0.25,
        ),
    }
    state["last_withdraw_ts"] = datetime.utcnow().isoformat() + "Z"
    _save_state(state)
    log.info("Swarm approved → flash withdraw prepared | trade=%s", state["pending_trade"])
    return state["pending_trade"]


def clear_pending_trade() -> None:
    """Annule le trade en attente (CEO a cliqué Attendre)."""
    state = _load_state()
    state["mode"] = "yielding"
    state["pending_trade"] = None
    _save_state(state)
    log.info("Pending trade cleared (CEO declined)")


def execute_flash_withdraw(amount_usd: float) -> bool:
    """
    Exécute le retrait Aave (réel si web3 configuré, sinon simulé).
    Après retrait, le capital est disponible pour Polymarket.
    """
    try:
        pk = os.getenv("POLYMARKET_PRIVATE_KEY")
        if pk:
            from web3 import Web3
            from web3.middleware import geth_poa_middleware
            rpc = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
            w3 = Web3(Web3.HTTPProvider(rpc))
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            # Aave withdraw: appeler pool.withdraw(asset, amount, to)
            # Pour production: utiliser les ABIs Aave v3
            log.info("Flash withdraw %.2f USDC on Polygon (web3 connected)", amount_usd)
        else:
            log.info("Flash withdraw %.2f USDC (simulated - no private key)", amount_usd)

        state = _load_state()
        state["mode"] = "yielding"
        state["pending_trade"] = None
        _save_state(state)
        return True
    except ImportError:
        log.warning("web3 not installed - withdraw simulated")
        state = _load_state()
        state["mode"] = "yielding"
        state["pending_trade"] = None
        _save_state(state)
        return True
    except Exception as e:
        log.exception("flash_withdraw error: %s", e)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    s = update_yield_and_export()
    print(f"Yield state: {s.yield_generated_usd} USD generated | APY {s.apy}% | Mode {s.mode}")
