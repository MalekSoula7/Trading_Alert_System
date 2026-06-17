"""
Forex market data via Twelve Data's REST API.

Free tier needs only an API key (twelvedata.com). It returns OHLC and, for many
FX pairs, a tick-volume figure. Free tier is rate limited (~8 requests/min,
limited daily credits) so keep the pair count and poll frequency modest.

Swap-in note: to use OANDA's v20 practice API instead (real-time, higher
quality, free demo account), implement the same get_ohlcv() signature in a new
class and point the engine at it. The rest of the bot does not care where bars
come from.
"""
from __future__ import annotations

import time
import requests
import pandas as pd

_BASE = "https://api.twelvedata.com/time_series"


class ForexFeed:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError(
                "No Twelve Data API key. Set TWELVEDATA_API_KEY in your .env "
                "(free at twelvedata.com), or plug in another forex feed."
            )
        self.api_key = api_key

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        params = {
            "symbol": symbol,
            "interval": timeframe,
            "outputsize": limit,
            "timezone": "UTC",
            "apikey": self.api_key,
        }
        for attempt in range(3):
            r = requests.get(_BASE, params=params, timeout=20)
            data = r.json()
            if data.get("status") == "error":
                # rate limit -> back off and retry
                if "limit" in data.get("message", "").lower():
                    time.sleep(15)
                    continue
                raise RuntimeError(f"Twelve Data error for {symbol}: {data.get('message')}")
            break
        else:
            raise RuntimeError(f"Twelve Data rate limited repeatedly for {symbol}")

        values = data.get("values", [])
        if not values:
            raise RuntimeError(f"No data returned for {symbol}")

        df = pd.DataFrame(values)
        df["ts"] = pd.to_datetime(df["datetime"], utc=True)
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(float) if "volume" in df else 0.0
        df = df.set_index("ts").sort_index()
        return df[["open", "high", "low", "close", "volume"]].iloc[:-1]
