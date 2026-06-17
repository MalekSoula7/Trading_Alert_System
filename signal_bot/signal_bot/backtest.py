"""
backtest.py — walk-forward backtester for the signal bot.

It replays history through the SAME engines the live bot uses
(analyze_crypto / analyze_forex) and the SAME indicators, so what you measure
here is exactly what the bot will alert on.

Key honesty features
--------------------
* No lookahead: at every step the engine only sees candles that had already
  closed at that moment (bias bars are filtered by close-time, not open-time).
* Indicators are causal (EMA/RSI/ATR/RVOL/VWAP only look backward), so they are
  computed once on the full series and then sliced — same values, much faster.
* Costs are modelled: entry slippage + round-trip fees (crypto) / spread (forex).
* Conservative intrabar fills: if a bar's range contains both the stop and the
  target, the stop is assumed hit first.
* One position per symbol at a time (you can't compound a setup you're already in).

Data
----
You provide ONE candle file/feed per symbol at the EXECUTION timeframe; the
higher-timeframe bias series is resampled from it, so alignment is automatic.

  Live fetch:   python backtest.py --market crypto --bars 4000
  From CSV:     python backtest.py --market crypto --source csv --csv-dir ./data
                (CSV columns: datetime/timestamp, open, high, low, close, volume)

Usage examples
--------------
  python backtest.py --market both --bars 5000 --tp-r 2 --be-r 1 --plot
  python backtest.py --market forex --symbols EUR/USD,GBP/USD --tp-r 1.5

Treat the numbers as a sanity check, not a promise. Out-of-sample + demo
forward-testing still come before real money.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

from config import CONFIG
from indicators import enrich
from strategies.crypto_momentum import analyze_crypto
from strategies.forex_session import analyze_forex


# --------------------------------------------------------------------------- #
#  Backtest settings                                                          #
# --------------------------------------------------------------------------- #
@dataclass
class BTConfig:
    start_equity: float = CONFIG.risk.account_balance
    risk_pct: float = CONFIG.risk.risk_per_trade
    tp_r: float = 2.0            # exit target in R multiples
    be_r: float | None = 1.0     # move stop to breakeven at +be_r (None to disable)
    # costs
    crypto_slippage_pct: float = 0.0005   # 5 bps entry slippage
    crypto_fee_pct: float = 0.0004        # 4 bps per side (taker)
    forex_slippage_pips: float = 0.3
    forex_spread_pips: float = 1.0


# --------------------------------------------------------------------------- #
#  Timeframe helpers                                                          #
# --------------------------------------------------------------------------- #
def tf_to_minutes(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("min"):
        return int(tf[:-3])
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 1440
    raise ValueError(f"Unrecognised timeframe: {tf}")


def resample_ohlcv(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    rule = f"{minutes}min"
    out = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna()
    return out


def pip_size(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


# --------------------------------------------------------------------------- #
#  Data loading                                                               #
# --------------------------------------------------------------------------- #
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    ts_col = cols.get("datetime") or cols.get("timestamp") or cols.get("date")
    if ts_col is None:
        raise ValueError(f"{path}: need a datetime/timestamp column")
    df["ts"] = pd.to_datetime(df[ts_col], utc=True)
    df = df.set_index("ts").sort_index()
    for c in ("open", "high", "low", "close"):
        df[c] = df[cols[c]].astype(float)
    df["volume"] = df[cols["volume"]].astype(float) if "volume" in cols else 0.0
    return df[["open", "high", "low", "close", "volume"]]


def fetch_crypto_history(symbol: str, tf: str, total: int) -> pd.DataFrame:
    import ccxt
    ex = getattr(ccxt, CONFIG.crypto.exchange)({"enableRateLimit": True})
    tf_ms = tf_to_minutes(tf) * 60_000
    since = ex.milliseconds() - total * tf_ms
    rows, limit = [], 1000
    while len(rows) < total:
        batch = ex.fetch_ohlcv(symbol, timeframe=tf, since=since, limit=limit)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + tf_ms
        if len(batch) < limit:
            break
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts").sort_index().iloc[:-1]


def fetch_forex_history(symbol: str, tf: str, total: int) -> pd.DataFrame:
    import requests
    key = CONFIG.runtime.twelvedata_key
    if not key:
        raise ValueError("TWELVEDATA_API_KEY not set — cannot fetch forex history.")
    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params={"symbol": symbol, "interval": tf, "outputsize": min(total, 5000),
                "timezone": "UTC", "apikey": key},
        timeout=30,
    )
    data = r.json()
    if data.get("status") == "error":
        raise RuntimeError(f"Twelve Data: {data.get('message')}")
    df = pd.DataFrame(data["values"])
    df["ts"] = pd.to_datetime(df["datetime"], utc=True)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype(float)
    df["volume"] = df["volume"].astype(float) if "volume" in df else 0.0
    return df.set_index("ts").sort_index()[["open", "high", "low", "close", "volume"]]


# --------------------------------------------------------------------------- #
#  Core walk-forward simulation                                               #
# --------------------------------------------------------------------------- #
def run_symbol(symbol: str, exec_raw: pd.DataFrame, market: str,
               bt: BTConfig) -> list[dict]:
    strat, risk = CONFIG.strat, CONFIG.risk
    if market == "crypto":
        exec_tf, bias_tf = CONFIG.crypto.exec_tf, CONFIG.crypto.bias_tf
    else:
        exec_tf, bias_tf = CONFIG.forex.exec_tf, CONFIG.forex.bias_tf

    exec_min, bias_min = tf_to_minutes(exec_tf), tf_to_minutes(bias_tf)
    bias_raw = resample_ohlcv(exec_raw, bias_min)

    ex = enrich(exec_raw, strat)
    bi = enrich(bias_raw, strat)

    # precompute bias close-times for fast, lookahead-safe slicing
    bias_close = bi.index + timedelta(minutes=bias_min)
    exec_close = ex.index + timedelta(minutes=exec_min)

    warmup = max(strat.ema_trend, strat.breakout_lookback + 2, strat.rvol_period) + 2
    n = len(ex)
    trades, pos = [], None
    pip = pip_size(symbol)

    for i in range(warmup, n):
        bar = ex.iloc[i]

        # ----- manage an open position on this (future) bar ----------- #
        if pos is not None:
            long = pos["dir"] == "LONG"
            hit = None
            if long:
                if bar["low"] <= pos["stop"]:
                    hit = ("stop", pos["stop"])
                elif bar["high"] >= pos["tp"]:
                    hit = ("tp", pos["tp"])
            else:
                if bar["high"] >= pos["stop"]:
                    hit = ("stop", pos["stop"])
                elif bar["low"] <= pos["tp"]:
                    hit = ("tp", pos["tp"])

            if hit:
                exit_price = hit[1]
                raw_r = ((exit_price - pos["entry"]) if long
                         else (pos["entry"] - exit_price)) / pos["risk"]
                # round-trip costs expressed in R
                if market == "crypto":
                    cost_price = (pos["entry"] + exit_price) * bt.crypto_fee_pct
                else:
                    cost_price = bt.forex_spread_pips * pip
                realized_r = raw_r - cost_price / pos["risk"]
                trades.append({
                    "symbol": symbol, "market": market, "dir": pos["dir"],
                    "entry_time": pos["entry_time"], "exit_time": ex.index[i],
                    "entry": pos["entry"], "exit": exit_price, "stop0": pos["stop0"],
                    "outcome": hit[0], "R": round(realized_r, 3),
                    "confidence": pos["confidence"],
                })
                pos = None
                continue  # no new entry on the bar we just exited

            # arm breakeven for NEXT bar (never on the current bar -> no optimism)
            if bt.be_r is not None and not pos["be_armed"]:
                be_level = (pos["entry"] + bt.be_r * pos["risk"] if long
                            else pos["entry"] - bt.be_r * pos["risk"])
                if (long and bar["high"] >= be_level) or (not long and bar["low"] <= be_level):
                    pos["stop"] = pos["entry"]
                    pos["be_armed"] = True
            continue

        # ----- flat: look for a new signal at this bar's close -------- #
        if i + 1 >= n:
            break
        cut = bias_close.searchsorted(exec_close[i], side="right")
        if cut < strat.ema_trend + 2:
            continue
        bias_slice = bi.iloc[:cut]
        exec_slice = ex.iloc[:i + 1]

        if market == "crypto":
            sig = analyze_crypto(symbol, exec_slice, bias_slice, strat, risk,
                                 exec_tf, bias_tf)
        else:
            ts = ex.index[i]
            h = ts.hour
            in_session = (ts.weekday() < 5 and
                          CONFIG.forex.session_start_utc <= h < CONFIG.forex.session_end_utc)
            if not in_session:
                continue
            label = "London/NY overlap" if 13 <= h < 16 else "London session"
            sig = analyze_forex(symbol, exec_slice, bias_slice, strat, risk,
                                exec_tf, bias_tf, label)

        if sig:
            long = sig.direction == "LONG"
            if market == "crypto":
                entry = sig.entry * (1 + bt.crypto_slippage_pct) if long \
                    else sig.entry * (1 - bt.crypto_slippage_pct)
            else:
                entry = sig.entry + bt.forex_slippage_pips * pip if long \
                    else sig.entry - bt.forex_slippage_pips * pip
            risk_price = abs(entry - sig.stop)
            if risk_price <= 0:
                continue
            tp = entry + bt.tp_r * risk_price if long else entry - bt.tp_r * risk_price
            pos = {
                "dir": sig.direction, "entry": entry, "stop": sig.stop,
                "stop0": sig.stop, "tp": tp, "risk": risk_price,
                "entry_time": ex.index[i], "be_armed": False,
                "confidence": sig.confidence,
            }
    return trades


# --------------------------------------------------------------------------- #
#  Metrics + reporting                                                        #
# --------------------------------------------------------------------------- #
def build_equity(trades: list[dict], bt: BTConfig) -> pd.DataFrame:
    eq = bt.start_equity
    rows = []
    for t in sorted(trades, key=lambda x: x["exit_time"]):
        eq *= (1 + bt.risk_pct * t["R"])
        rows.append({"exit_time": t["exit_time"], "equity": eq, "R": t["R"]})
    return pd.DataFrame(rows)


def metrics(trades: list[dict], eqdf: pd.DataFrame, bt: BTConfig) -> dict:
    if not trades:
        return {"trades": 0}
    rs = np.array([t["R"] for t in trades])
    wins, losses = rs[rs > 0], rs[rs <= 0]
    gross_win = wins.sum() if len(wins) else 0.0
    gross_loss = -losses.sum() if len(losses) else 0.0
    eq = eqdf["equity"].values
    peak = np.maximum.accumulate(eq)
    max_dd = ((peak - eq) / peak).max() if len(eq) else 0.0
    # longest losing streak
    streak = worst = 0
    for r in rs:
        streak = streak + 1 if r <= 0 else 0
        worst = max(worst, streak)
    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(rs),
        "avg_win_R": wins.mean() if len(wins) else 0.0,
        "avg_loss_R": losses.mean() if len(losses) else 0.0,
        "expectancy_R": rs.mean(),
        "profit_factor": (gross_win / gross_loss) if gross_loss else float("inf"),
        "total_return_pct": (eq[-1] / bt.start_equity - 1) * 100 if len(eq) else 0.0,
        "final_equity": eq[-1] if len(eq) else bt.start_equity,
        "max_drawdown_pct": max_dd * 100,
        "max_losing_streak": worst,
    }


def report(trades, bt: BTConfig, plot: bool):
    if not trades:
        print("\nNo trades generated. Try more bars, lower min_confidence, or a "
              "lower --tp-r.\n")
        return
    eqdf = build_equity(trades, bt)
    m = metrics(trades, eqdf, bt)

    print("\n" + "=" * 56)
    print(f"  BACKTEST RESULTS   ({m['trades']} trades)")
    print("=" * 56)
    print(f"  Win rate            {m['win_rate']:.1%}")
    print(f"  Expectancy          {m['expectancy_R']:+.3f} R / trade")
    print(f"  Avg win / avg loss  {m['avg_win_R']:+.2f}R / {m['avg_loss_R']:+.2f}R")
    print(f"  Profit factor       {m['profit_factor']:.2f}")
    print(f"  Total return        {m['total_return_pct']:+.1f}%  "
          f"(${bt.start_equity:,.0f} -> ${m['final_equity']:,.0f})")
    print(f"  Max drawdown        {m['max_drawdown_pct']:.1f}%")
    print(f"  Max losing streak   {m['max_losing_streak']}")
    print("=" * 56)

    # per-market / per-symbol breakdown
    tdf = pd.DataFrame(trades)
    by_sym = tdf.groupby("symbol")["R"].agg(["count", "mean", "sum"])
    print("\n  Per symbol (count | exp.R | total R):")
    for sym, row in by_sym.iterrows():
        print(f"    {sym:<12} {int(row['count']):>4} | {row['mean']:+.3f} | {row['sum']:+.2f}")

    tdf.to_csv("backtest_trades.csv", index=False)
    eqdf.to_csv("backtest_equity.csv", index=False)
    print("\n  Saved backtest_trades.csv and backtest_equity.csv")

    if plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.figure(figsize=(10, 4))
            plt.plot(eqdf["exit_time"], eqdf["equity"])
            plt.title("Equity curve")
            plt.xlabel("Time"); plt.ylabel("Equity"); plt.tight_layout()
            plt.savefig("backtest_equity.png", dpi=120)
            print("  Saved backtest_equity.png")
        except ImportError:
            print("  (install matplotlib for the equity-curve chart)")


# --------------------------------------------------------------------------- #
#  CLI                                                                        #
# --------------------------------------------------------------------------- #
def get_exec_data(symbol, market, source, csv_dir, bars):
    if source == "csv":
        path = os.path.join(csv_dir, symbol.replace("/", "") + ".csv")
        return load_csv(path)
    tf = CONFIG.crypto.exec_tf if market == "crypto" else CONFIG.forex.exec_tf
    return (fetch_crypto_history(symbol, tf, bars) if market == "crypto"
            else fetch_forex_history(symbol, tf, bars))


def main():
    ap = argparse.ArgumentParser(description="Backtest the signal bot strategies.")
    ap.add_argument("--market", choices=["crypto", "forex", "both"], default="both")
    ap.add_argument("--symbols", help="comma list, overrides config")
    ap.add_argument("--source", choices=["live", "csv"], default="live")
    ap.add_argument("--csv-dir", default="./data")
    ap.add_argument("--bars", type=int, default=4000, help="exec-TF candles to test")
    ap.add_argument("--tp-r", type=float, default=2.0)
    ap.add_argument("--be-r", type=float, default=1.0, help="set 0 to disable breakeven")
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args()

    bt = BTConfig(tp_r=args.tp_r, be_r=(None if args.be_r == 0 else args.be_r))

    markets = ["crypto", "forex"] if args.market == "both" else [args.market]
    all_trades = []
    for mkt in markets:
        if args.symbols:
            syms = [s.strip() for s in args.symbols.split(",")]
        else:
            syms = list(CONFIG.crypto.symbols if mkt == "crypto" else CONFIG.forex.symbols)
        for sym in syms:
            try:
                exec_raw = get_exec_data(sym, mkt, args.source, args.csv_dir, args.bars)
                trades = run_symbol(sym, exec_raw, mkt, bt)
                print(f"  {mkt} {sym}: {len(trades)} trades over {len(exec_raw)} bars")
                all_trades += trades
            except Exception as exc:
                print(f"  {mkt} {sym}: FAILED — {exc}")

    report(all_trades, bt, args.plot)


if __name__ == "__main__":
    main()
