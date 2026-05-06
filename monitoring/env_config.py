"""
NEXUS CAPITAL - .env config writer
Updates .env and triggers config refresh + scanner restart.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("nexus.env_config")

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
SCANNER_RESTART_REQUESTED = False


def set_env_values(updates: dict[str, str | int | float | bool]) -> bool:
    """Update multiple keys in .env in one write. Returns True if OK."""
    global SCANNER_RESTART_REQUESTED
    try:
        lines: list[str] = []
        keys_done: set[str] = set()
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("#"):
                    lines.append(line)
                    continue
                if "=" in line:
                    k = line.split("=", 1)[0].strip()
                    if k in updates:
                        val = updates[k]
                        val_str = str(val).lower() if isinstance(val, bool) else str(val)
                        lines.append(f"{k}={val_str}")
                        keys_done.add(k)
                        continue
                lines.append(line)
        for k, v in updates.items():
            if k not in keys_done:
                val_str = str(v).lower() if isinstance(v, bool) else str(v)
                lines.append(f"{k}={val_str}")
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        import os
        for k, v in updates.items():
            os.environ[k] = str(v).lower() if isinstance(v, bool) else str(v)
        _refresh_settings()
        SCANNER_RESTART_REQUESTED = True
        log.info("env_config: batch update %s", list(updates.keys()))
        return True
    except Exception as e:
        log.warning("env_config set_env_values error: %s", e)
        return False


def set_env_value(key: str, value: str | int | float | bool) -> bool:
    """Update key in .env and os.environ. Returns True if OK."""
    global SCANNER_RESTART_REQUESTED
    try:
        val_str = str(value).lower() if isinstance(value, bool) else str(value)
        lines: list[str] = []
        found = False
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("#"):
                    lines.append(line)
                    continue
                if "=" in line and line.split("=", 1)[0].strip() == key:
                    lines.append(f"{key}={val_str}")
                    found = True
                else:
                    lines.append(line)
        if not found:
            lines.append(f"{key}={val_str}")
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        import os
        os.environ[key] = val_str
        _refresh_settings()
        SCANNER_RESTART_REQUESTED = True
        log.info("env_config: %s=%s", key, val_str)
        if key == "SIMULATION_MODE":
            _sb_save_mode(val_str)
        return True
    except Exception as e:
        log.warning("env_config set_env_value error: %s", e)
        return False


def _refresh_settings() -> None:
    """Reload config from .env."""
    try:
        from dotenv import load_dotenv
        import config.settings as settings_module

        load_dotenv(ENV_PATH, override=True)
        settings_module.SETTINGS = settings_module.load_settings()
        settings_module.settings._s = settings_module.SETTINGS
    except Exception as e:
        log.warning("env_config refresh_settings: %s", e)


def request_scanner_restart() -> bool:
    """Returns True if restart was requested, then clears the flag."""
    global SCANNER_RESTART_REQUESTED
    if SCANNER_RESTART_REQUESTED:
        SCANNER_RESTART_REQUESTED = False
        return True
    return False


# ── Persistance du mode SIM/LIVE dans Supabase ───────────────────────────────

def _sb_save_mode(value: str) -> None:
    """Upsert SIMULATION_MODE dans la table bot_config de Supabase."""
    try:
        import os, httpx
        url = os.getenv("SUPABASE_URL", "").rstrip("/")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        if not url or not key:
            return
        with httpx.Client(timeout=5.0) as c:
            c.post(
                f"{url}/rest/v1/bot_config",
                headers={"apikey": key, "Authorization": f"Bearer {key}",
                         "Content-Type": "application/json",
                         "Prefer": "resolution=merge-duplicates"},
                json={"key": "SIMULATION_MODE", "value": value},
            )
        log.info("env_config: SIMULATION_MODE=%s persisté dans Supabase", value)
    except Exception as e:
        log.warning("_sb_save_mode: %s", e)


def restore_simulation_mode() -> None:
    """Lit SIMULATION_MODE depuis Supabase au démarrage et l'applique à os.environ."""
    try:
        import os, httpx
        url = os.getenv("SUPABASE_URL", "").rstrip("/")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        if not url or not key:
            return
        with httpx.Client(timeout=5.0) as c:
            r = c.get(
                f"{url}/rest/v1/bot_config",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                params={"key": "eq.SIMULATION_MODE", "select": "value", "limit": "1"},
            )
        if r.status_code == 200:
            rows = r.json()
            if rows and isinstance(rows, list):
                val = rows[0].get("value", "true")
                os.environ["SIMULATION_MODE"] = val
                _refresh_settings()
                log.info("restore_simulation_mode: SIMULATION_MODE=%s restauré depuis Supabase", val)
    except Exception as e:
        log.warning("restore_simulation_mode: %s (Railway env var utilisé)", e)
