"""
Entry point. Run with:  python main.py
Runs forever, scanning every poll_seconds. Ctrl-C to stop.
"""
from __future__ import annotations

import logging
import time

from config import CONFIG
from datafeeds.crypto import CryptoFeed
from datafeeds.forex import ForexFeed
from alerts.telegram import TelegramNotifier
from engine import Engine


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(CONFIG.runtime.log_file),
        ],
    )


def main():
    setup_logging()
    log = logging.getLogger("main")

    crypto_feed = CryptoFeed(CONFIG.crypto.exchange)

    # Forex is optional — if no key, the bot still runs crypto-only.
    try:
        forex_feed = ForexFeed(CONFIG.runtime.twelvedata_key)
    except ValueError as exc:
        log.warning("Forex disabled: %s", exc)
        forex_feed = None

    notifier = TelegramNotifier(CONFIG.runtime.telegram_token, CONFIG.runtime.telegram_chat_id)
    engine = Engine(CONFIG, crypto_feed, forex_feed, notifier)

    log.info("Signal bot started. Crypto=%s  Forex=%s  poll=%ss",
             list(CONFIG.crypto.symbols),
             list(CONFIG.forex.symbols) if forex_feed else "OFF",
             CONFIG.runtime.poll_seconds)

    while True:
        try:
            engine.scan()
        except Exception as exc:                    # keep the loop alive no matter what
            log.exception("scan cycle crashed: %s", exc)
        time.sleep(CONFIG.runtime.poll_seconds)


if __name__ == "__main__":
    main()
