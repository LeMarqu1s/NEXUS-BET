import asyncio
import logging
import os
import re
import time
from dotenv import load_dotenv
load_dotenv()


class _ApiKeyMaskFilter(logging.Filter):
    """Masks sensitive API keys in all log records."""
    _ODDS_KEY = os.getenv("ODDS_API_KEY", "")
    _PATTERNS = [
        re.compile(r"apiKey=[^&\s\"']+", re.IGNORECASE),
        re.compile(r"api_key=[^&\s\"']+", re.IGNORECASE),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        masked = msg
        for pat in self._PATTERNS:
            masked = pat.sub("apiKey=******", masked)
        if self._ODDS_KEY and len(self._ODDS_KEY) > 4 and self._ODDS_KEY in masked:
            masked = masked.replace(self._ODDS_KEY, "******")
        if masked != msg:
            record.msg = masked
            record.args = ()
        return True


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s - %(message)s")
_mask_filter = _ApiKeyMaskFilter()
logging.root.addFilter(_mask_filter)
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


async def main():
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
