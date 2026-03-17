#!/usr/bin/env python3
"""
NEXUS CAPITAL - First deploy welcome
Sends a welcome Telegram message on first deploy.
Run from Railway startCommand or as a one-shot after env is set.
"""
import os
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def send_welcome():
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        import urllib.request
        import urllib.parse
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": "🚀 NEXUS CAPITAL deployed successfully!\n\nDashboard: Check your Vercel URL\nTelegram: Bot is live",
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False

if __name__ == "__main__":
    ok = send_welcome()
    sys.exit(0 if ok else 1)
