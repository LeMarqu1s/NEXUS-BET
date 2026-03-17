#!/usr/bin/env python3
"""Test script: verify TELEGRAM_TOKEN and TELEGRAM_CHAT_ID work."""
import os
import sys
from pathlib import Path

# Manually load .env (no dotenv dependency)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("'\"").strip()
            if k and v and not k.startswith("#"):
                os.environ.setdefault(k, v)

import json
import urllib.request

def main():
    token = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    print("=" * 50)
    print("Telegram env check")
    print("=" * 50)
    print(f"TELEGRAM_TOKEN set: {bool(token)} (len={len(token) if token else 0})")
    print(f"TELEGRAM_CHAT_ID set: {bool(chat_id)} (value='{chat_id}')")
    
    if not token or not chat_id:
        print("\n[FAIL] Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return 1
    
    if token in ("ton_token", "ta_cle") or chat_id in ("ton_chat_id", "ta_cle"):
        print("\n[WARN] Placeholder values detected - replace with real credentials in .env")
        print("       Telegram API will reject placeholder tokens.")
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "🟢 NEXUS BET est en ligne. Scanner actif. Agents prêts.",
        "parse_mode": "HTML",
    }
    
    print("\nSending test message...")
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        print(f"Status: {r.status}")
        if data.get("ok"):
            print("[OK] Test message sent successfully")
            return 0
        print(f"[FAIL] API response: {data}")
        return 1
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            data = json.loads(body)
            print(f"[FAIL] HTTP {e.code}: {data}")
        except Exception:
            print(f"[FAIL] HTTP {e.code}: {body}")
        return 1
    except Exception as e:
        print(f"[FAIL] {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
