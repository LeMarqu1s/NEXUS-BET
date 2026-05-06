#!/usr/bin/env python3
"""
Migration : crée les tables scalp_trades et bot_config dans Supabase via Management API.
Usage : python scripts/create_scalp_trades.py
"""
import os
import sys

try:
    import httpx
except ImportError:
    print("ERROR: httpx non installé — pip install httpx")
    sys.exit(1)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

SQL = """
CREATE TABLE IF NOT EXISTS scalp_trades (
  id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  token_id    TEXT,
  side        TEXT,
  entry_price FLOAT,
  exit_price  FLOAT,
  pnl_usd     FLOAT,
  result      TEXT,
  opened_at   TIMESTAMPTZ,
  closed_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bot_config (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now()
);
"""

def run() -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL et SUPABASE_SERVICE_KEY doivent être définis")
        sys.exit(1)

    # Extrait le project ref depuis l'URL (https://XXXX.supabase.co → XXXX)
    ref = SUPABASE_URL.replace("https://", "").split(".")[0]

    with httpx.Client(timeout=15.0) as c:
        r = c.post(
            f"https://api.supabase.com/v1/projects/{ref}/database/query",
            headers={
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
            },
            json={"query": SQL.strip()},
        )

    if r.status_code in (200, 201):
        print("✅ Tables scalp_trades + bot_config créées (ou déjà existantes)")
    else:
        print(f"❌ Management API {r.status_code}: {r.text[:300]}")
        print()
        print("→ Lance ce SQL manuellement dans Supabase > SQL Editor :")
        print(SQL)
        sys.exit(1)


if __name__ == "__main__":
    run()
