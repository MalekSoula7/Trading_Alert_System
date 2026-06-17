"""
Central configuration for the signal bot.

Everything you would normally tweak lives here. Secrets (API keys, Telegram
token) are read from environment variables / a .env file so they never end up
in the code or in git. See .env.example.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


# --------------------------------------------------------------------------- #
#  Account / risk                                                             #
# --------------------------------------------------------------------------- #
@dataclass
class RiskConfig:
    account_balance: float = float(os.getenv("ACCOUNT_BALANCE", "1000"))
    risk_per_trade: float = 0.01          # 1% of balance risked per trade
    daily_loss_cap: float = 0.03          # informational: stop trading after -3% day
    # crypto stop = entry -/+ atr_mult * ATR ; same idea for forex
    atr_stop_mult: float = 1.2
    # R-multiple targets emitted on every signal
    target_r_multiples: tuple = (1.0, 2.0, 3.0)


# --------------------------------------------------------------------------- #
#  What to watch                                                              #
# --------------------------------------------------------------------------- #
@dataclass
class CryptoConfig:
    # ccxt exchange id used purely for *market data* (no keys, no trading)
    exchange: str = "binance"
    symbols: tuple = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
    bias_tf: str = "1h"       # higher timeframe = directional bias
    exec_tf: str = "5m"       # lower timeframe = entry trigger
    candles: int = 300        # how many candles to pull per request


@dataclass
class ForexConfig:
    # Free Twelve Data key (get one at twelvedata.com). Falls back gracefully.
    symbols: tuple = ("EUR/USD", "GBP/USD", "USD/JPY")
    bias_tf: str = "1h"
    exec_tf: str = "15min"     # Twelve Data uses "15min", "1h", "5min", etc.
    candles: int = 300
    # Only generate signals inside this UTC window (London + NY overlap).
    # 24h forex is open Sun 21:00 -> Fri 21:00 UTC, but we only act in prime hours.
    session_start_utc: int = 7     # 07:00 UTC ~ London open
    session_end_utc: int = 16      # 16:00 UTC ~ end of London/NY overlap
    pip_value_per_lot: float = 10.0  # rough $/pip per 1.0 standard lot for USD quote


# --------------------------------------------------------------------------- #
#  Strategy thresholds (tune after backtesting!)                              #
# --------------------------------------------------------------------------- #
@dataclass
class StrategyConfig:
    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend: int = 200
    rsi_period: int = 14
    atr_period: int = 14
    rvol_period: int = 20
    rvol_min: float = 1.3          # current volume must beat 1.3x the avg
    rsi_long_band: tuple = (50, 72)  # momentum present but not exhausted
    rsi_short_band: tuple = (28, 50)
    pullback_atr: float = 0.5      # "near the 20 EMA" = within 0.5 * ATR
    breakout_lookback: int = 20    # N-bar high/low for breakout detection
    min_confidence: int = 4        # 0-6 score; only alert at/above this


# --------------------------------------------------------------------------- #
#  Runtime                                                                    #
# --------------------------------------------------------------------------- #
@dataclass
class RuntimeConfig:
    poll_seconds: int = 300         # how often the loop wakes up (5 min)
    signal_cooldown_min: int = 120  # don't re-alert same symbol+side for 2h
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    twelvedata_key: str = os.getenv("TWELVEDATA_API_KEY", "")
    log_file: str = "signal_bot.log"


@dataclass
class Config:
    risk: RiskConfig = field(default_factory=RiskConfig)
    crypto: CryptoConfig = field(default_factory=CryptoConfig)
    forex: ForexConfig = field(default_factory=ForexConfig)
    strat: StrategyConfig = field(default_factory=StrategyConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)


CONFIG = Config()
