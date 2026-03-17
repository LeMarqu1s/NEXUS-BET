"""
NEXUS CAPITAL - Anti-Sybil / Mirror Trading Detector (Phase 6)
Détecte les patterns de Mirror Trading sur baleines cibles.
Déclenche l'alerte 🚨 ALERTE MANIPULATION si suspect.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

log = logging.getLogger("nexus.anti_sybil")

# Seuil : N trades similaires sur le même symbole/direction en fenêtre courte = suspect
MIRROR_THRESHOLD = 5
WINDOW_SYMBOLS: dict[str, list[float]] = defaultdict(list)


async def check_mirror_trading() -> bool:
    """
    Vérifie les smart money moves Unusual Whales pour patterns Mirror Trading.
    Retourne True si alerte envoyée.
    """
    try:
        from data.unusual_whales_mcp import UnusualWhalesMCPClient
        from monitoring.telegram_alerts import alert_anti_sybil
        from monitoring.telegram_wealth_manager import set_anti_sybil_alert

        client = UnusualWhalesMCPClient()
        moves = await client.get_smart_money_moves(limit=30)
        if not moves:
            return False

        # Regrouper par (symbol, direction) - heuristique simple
        buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for m in moves:
            sym = str(m.get("symbol", m.get("ticker", "")) or "").upper()
            side = str(m.get("side", m.get("direction", "")) or "BUY").upper()
            if sym:
                buckets[(sym, side)].append(m)

        for (sym, side), items in buckets.items():
            if len(items) >= MIRROR_THRESHOLD:
                details = (
                    f"Symbole {sym} | {side} | {len(items)} trades similaires détectés. "
                    "Pattern possible de copy-trading coordonné."
                )
                set_anti_sybil_alert(True, details)
                await alert_anti_sybil(details)
                log.warning("Anti-Sybil: %s", details)
                return True

        set_anti_sybil_alert(False, "")
        return False
    except ImportError:
        return False
    except Exception as e:
        log.debug("anti_sybil check: %s", e)
        return False
