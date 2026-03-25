"""
NEXUS BET - Auto-Optimizer
Analyse les performances des 24 dernières heures à 03:00 UTC et ajuste
automatiquement les seuils du sniper selon le win-rate par type de signal.

Seuils ajustés :
  MOMENTUM_THRESHOLD  — si win-rate MOMENTUM < 40% → +10%
  VOLUME_MULTIPLIER   — si win-rate VOLUME_SPIKE < 40% → +0.5
  SPREAD_THRESHOLD    — si win-rate SPREAD < 40% → +2%
  WHALE_THRESHOLD_USD — si win-rate WHALE < 40% → +20%
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("nexus.auto_optimizer")

_ROOT = Path(__file__).resolve().parent.parent
_PAPER_FILE = _ROOT / "logs" / "paper_trades.json"
_CONFIG_FILE = _ROOT / "logs" / "optimizer_config.json"

# Seuils par défaut (miroir de core/sniper.py)
_DEFAULTS: dict[str, float] = {
    "MOMENTUM_THRESHOLD": 0.05,
    "VOLUME_SPIKE_MULTIPLIER": 3.0,
    "SPREAD_THRESHOLD": 0.08,
    "WHALE_THRESHOLD_USD": 10_000.0,
}

WIN_RATE_MIN = 40.0    # % en dessous duquel on durcit le seuil
MIN_TRADES = 5         # minimum de trades pour ajuster (évite les petits échantillons)


# ── Chargement / sauvegarde config ────────────────────────────────────────────

def load_optimizer_config() -> dict[str, float]:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return dict(_DEFAULTS)


def save_optimizer_config(cfg: dict[str, float]) -> None:
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ── Analyse des trades paper ──────────────────────────────────────────────────

def _analyze_signal_performance() -> dict[str, dict[str, Any]]:
    """
    Lit logs/paper_trades.json et calcule le win-rate par type de signal
    pour les trades clôturés dans les dernières 24h.
    Retourne {signal_type: {wins, total, win_rate}}.
    """
    if not _PAPER_FILE.exists():
        return {}
    try:
        data = json.loads(_PAPER_FILE.read_text(encoding="utf-8"))
        trades = data.get("trades", [])
    except Exception as e:
        log.warning("auto_optimizer: cannot read paper trades: %s", e)
        return {}

    cutoff = time.time() - 86400  # 24h
    stats: dict[str, dict[str, int]] = {}

    for t in trades:
        if t.get("status") != "CLOSED":
            continue
        closed_at = float(t.get("closed_at") or 0)
        if closed_at < cutoff:
            continue
        # Détecte les types de signaux depuis les tags de la question/confiance
        # (Les paper trades n'ont pas de champ "signals" — on infère depuis le context)
        # Pour l'instant, on track "ALL" (global) et on utilise les colonnes disponibles
        signal_tags = []
        if t.get("confidence") and float(t["confidence"]) >= 0.50:
            signal_tags.append("HIGH_CONF")
        elif t.get("confidence"):
            signal_tags.append("LOW_CONF")

        won = float(t.get("pnl_usd") or 0) > 0
        for tag in signal_tags or ["ALL"]:
            if tag not in stats:
                stats[tag] = {"wins": 0, "total": 0}
            stats[tag]["total"] += 1
            if won:
                stats[tag]["wins"] += 1

    result = {}
    for tag, s in stats.items():
        wr = (s["wins"] / s["total"] * 100) if s["total"] > 0 else 0.0
        result[tag] = {"wins": s["wins"], "total": s["total"], "win_rate": round(wr, 1)}
    return result


def _analyze_sniper_signals() -> dict[str, dict[str, Any]]:
    """
    Lit les signaux bruts depuis paperclip_pending_signals.json et
    croise avec paper_trades.json pour calculer les win-rates par type.
    """
    pending_file = _ROOT / "paperclip_pending_signals.json"
    if not pending_file.exists():
        return {}

    # Analyse globale par type de signal (MOMENTUM, VOLUME_SPIKE, SPREAD, WHALE)
    if not _PAPER_FILE.exists():
        return {}
    try:
        paper_data = json.loads(_PAPER_FILE.read_text(encoding="utf-8"))
        trades = paper_data.get("trades", [])
    except Exception:
        return {}

    cutoff = time.time() - 86400
    stats: dict[str, dict[str, int]] = {
        "MOMENTUM": {"wins": 0, "total": 0},
        "VOLUME_SPIKE": {"wins": 0, "total": 0},
        "SPREAD": {"wins": 0, "total": 0},
        "WHALE": {"wins": 0, "total": 0},
    }

    for t in trades:
        if t.get("status") != "CLOSED":
            continue
        if float(t.get("closed_at") or 0) < cutoff:
            continue
        # Infère le type depuis question ou edge_pct (approximation)
        q = (t.get("question") or "").lower()
        won = float(t.get("pnl_usd") or 0) > 0
        # Tente d'inférer le type de signal depuis les données disponibles
        edge = float(t.get("edge_pct") or 0)
        if edge > 15:
            signal_type = "MOMENTUM"
        elif edge > 10:
            signal_type = "VOLUME_SPIKE"
        elif edge > 5:
            signal_type = "SPREAD"
        else:
            signal_type = "WHALE"
        stats[signal_type]["total"] += 1
        if won:
            stats[signal_type]["wins"] += 1

    result = {}
    for sig_type, s in stats.items():
        wr = (s["wins"] / s["total"] * 100) if s["total"] > 0 else 0.0
        result[sig_type] = {"wins": s["wins"], "total": s["total"], "win_rate": round(wr, 1)}
    return result


# ── Auto-ajustement des seuils ────────────────────────────────────────────────

def _adjust_thresholds(perf: dict[str, dict[str, Any]], cfg: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    """
    Ajuste les seuils du sniper selon les win-rates observés.
    Retourne (nouveau_cfg, liste_des_changements).
    """
    changes: list[str] = []
    new_cfg = dict(cfg)

    def tighten(key: str, delta: float, label: str) -> None:
        old = new_cfg.get(key, _DEFAULTS[key])
        new_val = round(old + delta, 4)
        new_cfg[key] = new_val
        changes.append(f"{label}: {old} → {new_val} (win-rate bas)")

    def relax(key: str, delta: float, label: str) -> None:
        old = new_cfg.get(key, _DEFAULTS[key])
        # Ne descend pas sous le défaut
        default = _DEFAULTS[key]
        new_val = round(max(default, old - delta), 4)
        if new_val < old:
            new_cfg[key] = new_val
            changes.append(f"{label}: {old} → {new_val} (win-rate bon)")

    for sig_type, s in perf.items():
        if s["total"] < MIN_TRADES:
            continue
        wr = s["win_rate"]

        if sig_type == "MOMENTUM":
            if wr < WIN_RATE_MIN:
                tighten("MOMENTUM_THRESHOLD", 0.005, "MOMENTUM seuil")  # +0.5%
            elif wr > 60:
                relax("MOMENTUM_THRESHOLD", 0.005, "MOMENTUM seuil")

        elif sig_type == "VOLUME_SPIKE":
            if wr < WIN_RATE_MIN:
                tighten("VOLUME_SPIKE_MULTIPLIER", 0.5, "VOLUME multiplicateur")
            elif wr > 60:
                relax("VOLUME_SPIKE_MULTIPLIER", 0.5, "VOLUME multiplicateur")

        elif sig_type == "SPREAD":
            if wr < WIN_RATE_MIN:
                tighten("SPREAD_THRESHOLD", 0.02, "SPREAD seuil")  # +2%
            elif wr > 60:
                relax("SPREAD_THRESHOLD", 0.01, "SPREAD seuil")

        elif sig_type == "WHALE":
            if wr < WIN_RATE_MIN:
                tighten("WHALE_THRESHOLD_USD", 2_000.0, "WHALE seuil USD")
            elif wr > 60:
                relax("WHALE_THRESHOLD_USD", 1_000.0, "WHALE seuil USD")

    return new_cfg, changes


# ── Rapport Telegram ──────────────────────────────────────────────────────────

async def _send_optimizer_report(perf: dict, changes: list[str], cfg: dict[str, float]) -> None:
    """Envoie le rapport d'optimisation à tous les abonnés actifs."""
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        return
    try:
        import telegram
        from monitoring.push_alerts import get_active_subscribers
        bot = telegram.Bot(token=token)
        users = await get_active_subscribers()
        fallback = os.getenv("TELEGRAM_CHAT_ID")
        if not users and fallback:
            users = [{"telegram_chat_id": fallback}]
        if not users:
            return

        L = "━━━━━━━━━━━━━━━"
        lines = [f"<b>🔧 AUTO-OPTIMIZER</b>\n{L}\n"]

        # Performances par signal
        lines.append("<code>WIN-RATES 24H\n")
        for sig_type, s in perf.items():
            if s["total"] == 0:
                continue
            icon = "✅" if s["win_rate"] >= WIN_RATE_MIN else "⚠️"
            lines.append(f"  {sig_type:<14} {s['win_rate']:.0f}% ({s['total']} trades) {icon}\n")
        lines.append("</code>\n")

        # Seuils actuels
        lines.append(
            f"{L}\n<code>"
            f"MOMENTUM   >{cfg.get('MOMENTUM_THRESHOLD', 0.05)*100:.1f}%\n"
            f"VOLUME     >{cfg.get('VOLUME_SPIKE_MULTIPLIER', 3.0):.1f}x\n"
            f"SPREAD     >{cfg.get('SPREAD_THRESHOLD', 0.08)*100:.1f}%\n"
            f"WHALE      >${cfg.get('WHALE_THRESHOLD_USD', 10000):.0f}"
            f"</code>\n"
        )

        # Changements
        if changes:
            lines.append(f"{L}\n<i>Ajustements :\n" + "\n".join(f"• {c}" for c in changes) + "</i>")
        else:
            lines.append(f"{L}\n<i>Seuils inchangés (données insuffisantes ou perf stable)</i>")

        message = "".join(lines)
        tasks = []
        for u in users:
            chat_id = u.get("telegram_chat_id")
            if chat_id:
                tasks.append(bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML"))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await bot.close()
        log.info("auto_optimizer: rapport envoyé à %d abonné(s)", len(tasks))
    except Exception as e:
        log.error("auto_optimizer: rapport Telegram échoué: %s", e)


# ── Boucle principale ─────────────────────────────────────────────────────────

async def run_auto_optimizer() -> None:
    """Boucle principale : optimise à 03:00 UTC chaque jour."""
    log.info("Auto-optimizer démarré — optimisation quotidienne à 03:00 UTC")
    while True:
        now = datetime.now(timezone.utc)
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if now >= target:
            import datetime as _dt
            target = target + _dt.timedelta(days=1)
        wait_sec = (target - now).total_seconds()
        log.info("Auto-optimizer : prochaine optimisation dans %.0fh", wait_sec / 3600)
        await asyncio.sleep(wait_sec)

        try:
            log.info("Auto-optimizer : analyse en cours...")
            perf = _analyze_sniper_signals()
            cfg = load_optimizer_config()
            new_cfg, changes = _adjust_thresholds(perf, cfg)

            if changes:
                save_optimizer_config(new_cfg)
                log.info("Auto-optimizer : %d ajustement(s) — %s", len(changes), changes)
                # Appliquer les seuils au sniper en live
                try:
                    import core.sniper as _sniper
                    for key, val in new_cfg.items():
                        if hasattr(_sniper, key):
                            setattr(_sniper, key, val)
                            log.info("Sniper.%s = %s (auto-optimisé)", key, val)
                except Exception as e:
                    log.warning("auto_optimizer: application seuils sniper: %s", e)
            else:
                log.info("Auto-optimizer : aucun ajustement nécessaire")

            await _send_optimizer_report(perf, changes, new_cfg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Auto-optimizer erreur: %s", e)
