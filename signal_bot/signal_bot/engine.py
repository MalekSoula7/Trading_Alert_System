"""
The engine ties everything together:
  - pulls bias + exec candles for each symbol
  - enriches with indicators
  - runs the correct strategy per market
  - gates forex by session/weekday
  - de-duplicates so you aren't pinged about the same setup every cycle
  - sends Telegram alerts
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from indicators import enrich
from strategies.crypto_momentum import analyze_crypto
from strategies.forex_session import analyze_forex
from risk import size_signal

log = logging.getLogger("engine")


class Engine:
    def __init__(self, config, crypto_feed, forex_feed, notifier):
        self.cfg = config
        self.crypto_feed = crypto_feed
        self.forex_feed = forex_feed
        self.notifier = notifier
        self._last_alert = {}  # (market, symbol, direction) -> datetime

    # ----- de-dup ---------------------------------------------------------- #
    def _should_alert(self, sig) -> bool:
        key = (sig.market, sig.symbol, sig.direction)
        now = datetime.now(timezone.utc)
        last = self._last_alert.get(key)
        cooldown = self.cfg.runtime.signal_cooldown_min * 60
        if last and (now - last).total_seconds() < cooldown:
            return False
        self._last_alert[key] = now
        return True

    def _dispatch(self, sig) -> None:
        if not self._should_alert(sig):
            log.info("Suppressed (cooldown): %s %s %s", sig.market, sig.symbol, sig.direction)
            return
        size_signal(sig, self.cfg.risk, self.cfg.forex)
        self.notifier.send(sig.to_telegram())

    # ----- forex session gate --------------------------------------------- #
    def _forex_session(self):
        now = datetime.now(timezone.utc)
        if now.weekday() >= 5:                      # Sat/Sun
            return None
        h = now.hour
        if not (self.cfg.forex.session_start_utc <= h < self.cfg.forex.session_end_utc):
            return None
        return "London/NY overlap" if 13 <= h < 16 else "London session"

    # ----- one full scan --------------------------------------------------- #
    def scan(self) -> None:
        self._scan_crypto()
        self._scan_forex()

    def _scan_crypto(self):
        c = self.cfg.crypto
        for sym in c.symbols:
            try:
                bias = enrich(self.crypto_feed.get_ohlcv(sym, c.bias_tf, c.candles), self.cfg.strat)
                exe = enrich(self.crypto_feed.get_ohlcv(sym, c.exec_tf, c.candles), self.cfg.strat)
                sig = analyze_crypto(sym, exe, bias, self.cfg.strat, self.cfg.risk,
                                     c.exec_tf, c.bias_tf)
                if sig:
                    self._dispatch(sig)
            except Exception as exc:                # never let one symbol kill the loop
                log.error("crypto %s failed: %s", sym, exc)

    def _scan_forex(self):
        session = self._forex_session()
        if session is None:
            log.info("Forex market outside trading session — skipping FX scan.")
            return
        if self.forex_feed is None:
            return
        f = self.cfg.forex
        for sym in f.symbols:
            try:
                bias = enrich(self.forex_feed.get_ohlcv(sym, f.bias_tf, f.candles), self.cfg.strat)
                exe = enrich(self.forex_feed.get_ohlcv(sym, f.exec_tf, f.candles), self.cfg.strat)
                sig = analyze_forex(sym, exe, bias, self.cfg.strat, self.cfg.risk,
                                    f.exec_tf, f.bias_tf, session)
                if sig:
                    self._dispatch(sig)
            except Exception as exc:
                log.error("forex %s failed: %s", sym, exc)
