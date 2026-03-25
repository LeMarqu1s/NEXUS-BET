"""
NEXUS BET - Auto-Optimizer (6h loop)
Toutes les 6 heures, backtest les signaux détectés depuis Supabase
ou le fichier local, calcule les stats par trigger et ajuste les seuils.
Envoie un rapport Telegram au format spécifié.
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

import httpx

log = logging.getLogger("nexus.auto_optimizer")

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _ROOT / "logs" / "optimizer_config.json"

# ── Seuils par défaut ─────────────────────────────────────────────────────────
_DEFAULTS: dict[str, float] = {
    "MOMENTUM_THRESHOLD": 0.05,
    "VOLUME_SPIKE_MULTIPLIER": 3.0,
    "SPREAD_THRESHOLD": 0.08,
    "WHALE_THRESHOLD_USD": 10_000.0,
}

WIN_RATE_RAISE  = 45.0       # % WR en dessous duquel on durcit le seuil
WIN_RATE_LOWER  = 70.0       # % WR au dessus duquel on peut assouplir
MIN_TRADES      = 3          # minimum pour ajuster (évite petits échantillons)
LOOP_INTERVAL   = 6 * 3600   # 6 heures
BACKTEST_HOURS  = 6          # fenêtre backtest = 6h


# ── Config ────────────────────────────────────────────────────────────────────

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


# ── Fetch signaux (6h) ────────────────────────────────────────────────────────

async def _fetch_signals_6h() -> list[dict]:
    """
    Récupère les signaux des 6 dernières heures.
    Priorité : Supabase → fichier local paperclip_pending_signals.json.
    """
    cutoff_ts = time.time() - BACKTEST_HOURS * 3600

    # 1. Essai Supabase
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if url and key:
        try:
            cutoff_iso = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).isoformat()
            async with httpx.AsyncClient(timeout=8.0) as c:
                r = await c.get(
                    f"{url}/rest/v1/signals",
                    headers={"apikey": key, "Authorization": f"Bearer {key}"},
                    params={
                        "created_at": f"gte.{cutoff_iso}",
                        "select": "market_id,side,edge_pct,confidence,polymarket_price,signal_strength,created_at",
                        "limit": "200",
                        "order": "created_at.desc",
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list) and data:
                        log.info("optimizer: %d signaux Supabase (6h)", len(data))
                        return data
        except Exception as e:
            log.debug("_fetch_signals_6h Supabase: %s", e)

    # 2. Fallback : fichier local (contient les 50 derniers signaux en mémoire)
    try:
        local_paths = [
            _ROOT / "paperclip_pending_signals.json",
            _ROOT / "logs" / "paperclip_pending_signals.json",
        ]
        for p in local_paths:
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                sigs = d.get("signals", []) if isinstance(d, dict) else []
                # Filtrer par timestamp si disponible
                recent = []
                for s in sigs:
                    ts = s.get("created_at") or s.get("timestamp")
                    if ts:
                        try:
                            sig_ts = float(ts) if str(ts).isdigit() else \
                                     datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
                            if sig_ts >= cutoff_ts:
                                recent.append(s)
                        except Exception:
                            recent.append(s)  # inclure si parsing impossible
                    else:
                        recent.append(s)
                if recent:
                    log.info("optimizer: %d signaux depuis fichier local (6h)", len(recent))
                    return recent
    except Exception as e:
        log.debug("_fetch_signals_6h local: %s", e)

    return []


# ── Simulation (backtest sans résolution réelle) ──────────────────────────────

def _classify_trigger(sig: dict) -> str:
    """Classifie un signal par type de trigger."""
    strength = (sig.get("signal_strength") or "").upper()
    edge = float(sig.get("edge_pct") or 0)
    if "VOLUME" in strength or edge > 15:
        return "VOLUME_SPIKE"
    if "MOMENTUM" in strength or edge > 10:
        return "MOMENTUM"
    if "WHALE" in strength:
        return "WHALE_ENTRY"
    if "SPREAD" in strength or edge > 5:
        return "SPREAD"
    if edge > 0:
        return "MOMENTUM"  # default for low-edge signals
    return "SPREAD"


def _simulate_outcome(sig: dict) -> bool:
    """
    Simulation backtest : un signal 'aurait gagné' si :
    - confidence >= 0.60  ET  edge_pct >= 5%
    Logique conservative basée sur nos critères de qualité de signal.
    """
    conf  = float(sig.get("confidence") or 0)
    edge  = float(sig.get("edge_pct")   or 0)
    return conf >= 0.60 and edge >= 5.0


def _compute_backtest_stats(signals: list[dict]) -> dict[str, dict[str, Any]]:
    """
    Calcule les stats de backtest par trigger.
    Retourne {trigger: {wins, total, win_rate}}.
    """
    stats: dict[str, dict] = {
        t: {"wins": 0, "total": 0}
        for t in ("VOLUME_SPIKE", "MOMENTUM", "WHALE_ENTRY", "SPREAD")
    }

    for sig in signals:
        trigger = _classify_trigger(sig)
        if trigger not in stats:
            stats[trigger] = {"wins": 0, "total": 0}
        won = _simulate_outcome(sig)
        stats[trigger]["total"] += 1
        if won:
            stats[trigger]["wins"] += 1

    # Calculer win_rate
    for t, s in stats.items():
        s["win_rate"] = round(s["wins"] / s["total"] * 100, 1) if s["total"] > 0 else 0.0

    return stats


def _calc_simulated_pnl(
    signals: list[dict],
    current_capital: float,
    avg_return_pct: float = 15.0,
    avg_loss_pct: float = 2.5,
) -> float:
    """Calcule le P&L simulé sur les signaux détectés."""
    n = len(signals)
    if n == 0:
        return 0.0
    wins   = sum(1 for s in signals if _simulate_outcome(s))
    losses = n - wins
    per_trade = max(1.0, round(current_capital * 0.05, 2))  # 5% du capital par trade
    return round(wins * per_trade * (avg_return_pct / 100) - losses * per_trade * (avg_loss_pct / 100), 2)


# ── Auto-ajustement des seuils ────────────────────────────────────────────────

def _adjust_thresholds(
    stats: dict[str, dict], cfg: dict[str, float]
) -> tuple[dict[str, float], list[str]]:
    """Ajuste les seuils selon win-rate. Retourne (new_cfg, changes_list)."""
    new_cfg = dict(cfg)
    changes: list[str] = []

    mapping = {
        "MOMENTUM":    ("MOMENTUM_THRESHOLD",     0.005, 0.005),
        "VOLUME_SPIKE":("VOLUME_SPIKE_MULTIPLIER", 0.5,   0.5),
        "SPREAD":      ("SPREAD_THRESHOLD",        0.02,  0.01),
        "WHALE_ENTRY": ("WHALE_THRESHOLD_USD",     2000.0, 1000.0),
    }

    for trigger, (key, step_up, step_down) in mapping.items():
        s = stats.get(trigger, {})
        n = s.get("total", 0)
        wr = s.get("win_rate", 0.0)
        if n < MIN_TRADES:
            continue
        old = new_cfg.get(key, _DEFAULTS.get(key, 0))
        if wr < WIN_RATE_RAISE:
            new_val = round(old + step_up, 4)
            new_cfg[key] = new_val
            changes.append(f"{trigger}: {wr:.0f}% WR → seuil {old} → {new_val} (+)")
        elif wr > WIN_RATE_LOWER:
            new_val = round(max(_DEFAULTS.get(key, 0), old - step_down), 4)
            if new_val < old:
                new_cfg[key] = new_val
                changes.append(f"{trigger}: {wr:.0f}% WR → seuil {old} → {new_val} (-)")

    return new_cfg, changes


# ── Rapport Telegram (format exact demandé) ───────────────────────────────────

async def _send_report(
    signals: list[dict],
    stats:   dict[str, dict],
    changes: list[str],
    current_capital: float,
) -> None:
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

        # Totaux
        total_sigs = len(signals)
        total_wins  = sum(1 for s in signals if _simulate_outcome(s))
        total_loss  = total_sigs - total_wins
        overall_wr  = round(total_wins / total_sigs * 100) if total_sigs else 0
        sim_pnl     = _calc_simulated_pnl(signals, current_capital)
        pnl_sign    = "+" if sim_pnl >= 0 else ""

        L = "━━━━━━━━━━━━━━━━━━━━"

        # Lignes par trigger
        trigger_emojis = {
            "VOLUME_SPIKE": "🔥",
            "MOMENTUM":     "📈",
            "WHALE_ENTRY":  "🐋",
            "SPREAD":       "📉",
        }
        trigger_lines = ""
        for trigger, emoji in trigger_emojis.items():
            s = stats.get(trigger, {})
            if s.get("total", 0) == 0:
                continue
            wr_t = s["win_rate"]
            trigger_lines += f"{emoji} {trigger} : {s['wins']}/{s['total']} ({wr_t:.0f}%)\n"

        # Ligne auto-ajustement
        if changes:
            adj_text = "\n".join(f"  • {c}" for c in changes[:4])
            adj_line = f"→ Auto-ajustement :\n{adj_text}"
        else:
            adj_line = "→ Auto-ajustement : aucun (seuils stables)"

        text = (
            f"🤖 <b>RAPPORT AUTO-BACKTEST</b>\n{L}\n"
            f"📊 Période : {BACKTEST_HOURS} dernières heures\n"
            f"🎯 Signaux détectés : <b>{total_sigs}</b>\n"
            f"✅ Auraient gagné : <b>{total_wins}</b>  "
            f"❌ Auraient perdu : <b>{total_loss}</b>\n"
            f"📈 Win Rate : <b>{overall_wr}%</b>\n"
            f"💰 P&amp;L simulé : <b>{pnl_sign}${abs(sim_pnl):.2f}</b> "
            f"sur capital ${current_capital:.2f}\n"
            f"{L}\n"
            f"<b>Par trigger :</b>\n{trigger_lines}"
            f"{L}\n"
            f"<i>{adj_line}</i>"
        )

        tasks = []
        for u in users:
            cid = u.get("telegram_chat_id")
            if cid:
                tasks.append(
                    bot.send_message(chat_id=cid, text=text, parse_mode="HTML")
                )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await bot.close()
        log.info("auto_optimizer: rapport envoyé à %d subscriber(s)", len(tasks))
    except Exception as e:
        log.error("auto_optimizer: rapport Telegram: %s", e)


# ── Boucle principale ─────────────────────────────────────────────────────────

async def run_auto_optimizer() -> None:
    """Boucle principale : backteste et optimise toutes les 6 heures."""
    log.info(
        "Auto-optimizer démarré — boucle %dh | WR_RAISE=%.0f%% WR_LOWER=%.0f%%",
        BACKTEST_HOURS, WIN_RATE_RAISE, WIN_RATE_LOWER,
    )

    # Premier run après 5min (laisser le bot démarrer)
    await asyncio.sleep(300)

    while True:
        try:
            log.info("Auto-optimizer : cycle %dh démarré…", BACKTEST_HOURS)

            # Capital actuel
            current_capital = 50.0
            try:
                from core.compounder import get_state as _compound_state
                current_capital = _compound_state().get("capital", 50.0)
            except Exception:
                try:
                    current_capital = float(os.getenv("PAPER_CAPITAL_USD", "50"))
                except Exception:
                    pass

            signals = await _fetch_signals_6h()
            log.info("Auto-optimizer : %d signaux détectés en %dh", len(signals), BACKTEST_HOURS)

            stats   = _compute_backtest_stats(signals)
            cfg     = load_optimizer_config()
            new_cfg, changes = _adjust_thresholds(stats, cfg)

            if changes:
                save_optimizer_config(new_cfg)
                log.info("Auto-optimizer : %d ajustement(s) — %s", len(changes), changes)
                # Appliquer en live au sniper si importé
                try:
                    import core.sniper as _sniper
                    for k, v in new_cfg.items():
                        if hasattr(_sniper, k):
                            setattr(_sniper, k, v)
                except Exception as e:
                    log.debug("apply thresholds: %s", e)
            else:
                log.info("Auto-optimizer : aucun ajustement")

            await _send_report(signals, stats, changes, current_capital)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Auto-optimizer erreur: %s", e)

        log.info("Auto-optimizer : prochain cycle dans %dh", BACKTEST_HOURS)
        await asyncio.sleep(LOOP_INTERVAL)
