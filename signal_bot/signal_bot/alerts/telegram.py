"""Send alerts to Telegram via the Bot API (just an HTTPS POST, no library)."""
from __future__ import annotations

import logging
import requests

log = logging.getLogger("alerts")


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        if not self.enabled:
            log.warning("Telegram not configured — alerts will print to console only.")

    def send(self, text: str) -> None:
        print("\n" + "=" * 50 + "\n" + text + "\n" + "=" * 50)  # always log locally
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            r = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=15,
            )
            if r.status_code != 200:
                log.error("Telegram send failed: %s %s", r.status_code, r.text)
        except requests.RequestException as exc:
            log.error("Telegram send error: %s", exc)
