"""
Crypto market data via ccxt. Uses only public OHLCV endpoints, so NO API key
and NO trading permissions are involved — this bot never places orders.
"""
from __future__ import annotations

import pandas as pd
import ccxt


class CryptoFeed:
    def __init__(self, exchange_id: str = "binance"):
        self.exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        raw = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(
            raw, columns=["ts", "open", "high", "low", "close", "volume"]
        )
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df = df.set_index("ts").sort_index()
        # drop the still-forming last candle so signals fire on closed bars only
        return df.iloc[:-1]
