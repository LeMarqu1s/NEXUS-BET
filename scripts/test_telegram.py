#!/usr/bin/env python3
"""
NEXUS BET - Test Telegram Bot "Pro"
Envoie un message premium formaté avec InlineKeyboardMarkup.
Usage: python scripts/test_telegram.py
"""
import os
import sys
import time
from pathlib import Path

import httpx

# Charger .env
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("'\"").strip()
            if k and v and not k.startswith("#"):
                os.environ.setdefault(k, v)


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    print("=" * 50)
    print("Telegram Bot Pro - Test")
    print("=" * 50)
    print(f"TELEGRAM_BOT_TOKEN: {'✓' if token else '✗'}")
    print(f"TELEGRAM_CHAT_ID: {'✓' if chat_id else '✗'}")

    if not token or not chat_id:
        print("\n[FAIL] Configure TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans .env")
        return 1

    # Message premium formaté
    msg = (
        "🟢 <b>OPPORTUNITÉ</b>\n\n"
        "📊 <b>Edge:</b> 4.2%\n"
        "💰 <b>Kelly:</b> 12.5%\n"
        "📈 <b>Side:</b> YES | Confiance: 78%\n\n"
        "<i>Will Bitcoin exceed $100k by end of 2025?</i>"
    )

    # InlineKeyboardMarkup: [Investiguer] [Forcer l'achat] [Ignorer]
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🔍 Investiguer", "callback_data": "inv_test_market"},
                {"text": "💰 Forcer l'achat", "callback_data": "buy_test_market"},
                {"text": "⏭ Ignorer", "callback_data": "ignore_test_market"},
            ]
        ]
    }

    payload = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": reply_markup,
    }

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    max_retries = 3
    retry_delay = 3.0  # secondes entre chaque tentative (WinError 10054 nécessite un délai)

    # Court délai avant la 1ère tentative pour éviter connexion "à froid"
    time.sleep(0.5)

    for attempt in range(1, max_retries + 1):
        print(f"\nEnvoi du message premium (tentative {attempt}/{max_retries})...")
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.post(url, json=payload)
            # Session fermée automatiquement par le contexte 'with'
            data = r.json()
            if r.status_code == 200 and data.get("ok"):
                print("[OK] Message envoyé avec succès")
                return 0
            print(f"[FAIL] API HTTP {r.status_code}: {data}")
            if attempt < max_retries:
                print(f"  → Nouvelle tentative dans {retry_delay}s...")
                time.sleep(retry_delay)
        except (httpx.HTTPError, OSError, ConnectionError) as e:
            # OSError inclut WinError 10054 (connexion forcée fermée par l'hôte distant)
            print(f"[FAIL] Erreur réseau (tentative {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                print(f"  → Nouvelle tentative dans {retry_delay}s...")
                time.sleep(retry_delay)
        except Exception as e:
            print(f"[FAIL] {e}")
            if attempt < max_retries:
                print(f"  → Nouvelle tentative dans {retry_delay}s...")
                time.sleep(retry_delay)

    print("\n[FAIL] Échec après 3 tentatives")
    return 1


if __name__ == "__main__":
    sys.exit(main())
