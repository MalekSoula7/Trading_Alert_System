"""
Pure-pandas indicator functions. No pandas-ta / talib dependency so this stays
portable and unbreakable across numpy/pandas versions.

Every function takes a DataFrame with columns: open, high, low, close, volume
and a UTC DatetimeIndex, and returns a pandas Series aligned to that index.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder smoothing
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low),
         (high - prev_close).abs(),
         (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def rvol(volume: pd.Series, period: int = 20) -> pd.Series:
    """Relative volume = current bar volume / rolling average volume."""
    avg = volume.rolling(period).mean()
    return volume / avg.replace(0, np.nan)


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Intraday VWAP that resets at 00:00 UTC each day.
    Needs real volume, so it is only meaningful for crypto. Returns NaN if
    volume is all zero (e.g. some forex feeds).
    """
    if df["volume"].fillna(0).sum() == 0:
        return pd.Series(np.nan, index=df.index)
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    day = df.index.normalize()
    cum_vol = df["volume"].groupby(day).cumsum()
    cum_vp = (typical * df["volume"]).groupby(day).cumsum()
    return cum_vp / cum_vol.replace(0, np.nan)


def enrich(df: pd.DataFrame, strat) -> pd.DataFrame:
    """Attach all indicator columns the strategies need."""
    out = df.copy()
    out["ema_fast"] = ema(out["close"], strat.ema_fast)
    out["ema_slow"] = ema(out["close"], strat.ema_slow)
    out["ema_trend"] = ema(out["close"], strat.ema_trend)
    out["rsi"] = rsi(out["close"], strat.rsi_period)
    out["atr"] = atr(out, strat.atr_period)
    out["rvol"] = rvol(out["volume"], strat.rvol_period)
    out["vwap"] = session_vwap(out)
    return out
