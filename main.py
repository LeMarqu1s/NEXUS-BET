import asyncio
import logging
import time
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s - %(message)s")
log = logging.getLogger("NEXUS")


async def run_scanner():
    from core.scanner_ws import run_forever
    while True:
        try:
            await run_forever()
        except Exception as e:
            log.error("Scanner crashed: %s, restart in 5s", e)
            await asyncio.sleep(5)


async def run_telegram():
    from monitoring.telegram_bot import run_forever
    while True:
        try:
            await run_forever()
        except Exception as e:
            log.error("Telegram crashed: %s, restart in 5s", e)
            await asyncio.sleep(5)


def check_env():
    import os
    issues = []
    required = {
        "SUPABASE_URL": "URL projet Supabase (Settings → API)",
        "SUPABASE_ANON_KEY": "Clé anon public Supabase (Settings → API)",
        "TELEGRAM_BOT_TOKEN": "Token bot Telegram (@BotFather)",
        "TELEGRAM_CHAT_ID": "Ton chat ID Telegram",
    }
    for key, desc in required.items():
        val = os.getenv(key, "")
        if not val:
            issues.append(f"  ❌ MANQUANT: {key}  ({desc})")
        else:
            masked = val[:8] + "..." if len(val) > 8 else "***"
            log.info("  ✅ %s = %s", key, masked)
    if issues:
        log.warning("=" * 60)
        log.warning("VARIABLES MANQUANTES — Supabase ne fonctionnera PAS :")
        for issue in issues:
            log.warning(issue)
        log.warning("→ Ajoute-les dans Railway → Variables")
        log.warning("=" * 60)
    else:
        log.info("Toutes les variables critiques sont présentes.")


async def main():
    check_env()
    log.info("NEXUS BET starting...")
    await asyncio.gather(
        run_scanner(),
        run_telegram(),
        return_exceptions=True,
    )


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            log.error("Fatal: %s, restart in 10s", e)
            time.sleep(10)
