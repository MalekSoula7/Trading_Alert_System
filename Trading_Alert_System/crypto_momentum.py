"""
CRYPTO engine — momentum + pullback, 24/7, VWAP-anchored.

Logic (long; short is the mirror):
  BIAS  (higher TF, e.g. 1h):
     price above 200 EMA            -> uptrend context
  TREND (exec TF, e.g. 5m):
     20 EMA above 50 EMA            -> aligned short-term trend
     price above session VWAP       -> trading on the strong side of the day
  TRIGGER (one of):
     (a) pullback to ~20 EMA then a bullish reclaim candle, OR
     (b) breakout above the N-bar high
  CONFIRM:
     RSI inside momentum band (not exhausted)
     RVOL above threshold (volume conviction)
     ATR expanding (not dead chop)

Each satisfied block adds to a 0-6 confidence score. Stop = entry - mult*ATR.
"""
from __future__ import annotations

from typing import Optional
import pandas as pd

from .base import Signal


def analyze_crypto(symbol, df_exec, df_bias, strat, risk, exec_tf, bias_tf) -> Optional[Signal]:
    e = df_exec.iloc[-1]          # last closed exec candle
    prev = df_exec.iloc[-2]
    b = df_bias.iloc[-1]

    atr_now = e["atr"]
    if pd.isna(atr_now) or atr_now == 0:
        return None
    atr_avg = df_exec["atr"].rolling(strat.rvol_period).mean().iloc[-1]
    atr_expanding = atr_now >= atr_avg

    recent_high = df_exec["high"].iloc[-(strat.breakout_lookback + 1):-1].max()
    recent_low = df_exec["low"].iloc[-(strat.breakout_lookback + 1):-1].min()
    rvol_ok = (not pd.isna(e["rvol"])) and e["rvol"] >= strat.rvol_min
    vwap = e["vwap"]

    for direction in ("LONG", "SHORT"):
        long = direction == "LONG"
        reasons, score = [], 0

        # --- BIAS -------------------------------------------------------
        bias_ok = b["close"] > b["ema_trend"] if long else b["close"] < b["ema_trend"]
        if not bias_ok:
            continue
        score += 1
        reasons.append(f"{bias_tf} trend: price {'above' if long else 'below'} 200 EMA")

        # --- TREND ------------------------------------------------------
        stack_ok = e["ema_fast"] > e["ema_slow"] if long else e["ema_fast"] < e["ema_slow"]
        if not stack_ok:
            continue
        score += 1
        reasons.append(f"{exec_tf} 20/50 EMA aligned {'up' if long else 'down'}")

        if not pd.isna(vwap):
            vwap_ok = e["close"] > vwap if long else e["close"] < vwap
            if vwap_ok:
                score += 1
                reasons.append(f"Price on the {'bull' if long else 'bear'} side of session VWAP")

        # --- TRIGGER: pullback-reclaim OR breakout ----------------------
        near_ema = abs(prev["low" if long else "high"] - prev["ema_fast"]) <= strat.pullback_atr * atr_now
        reclaim = (e["close"] > e["ema_fast"] and e["close"] > e["open"]) if long \
            else (e["close"] < e["ema_fast"] and e["close"] < e["open"])
        pullback_trigger = near_ema and reclaim
        breakout_trigger = e["close"] > recent_high if long else e["close"] < recent_low
        if not (pullback_trigger or breakout_trigger):
            continue
        score += 1
        reasons.append("Pullback-and-reclaim" if pullback_trigger else "Breakout of recent range")

        # --- CONFIRM ----------------------------------------------------
        lo, hi = strat.rsi_long_band if long else strat.rsi_short_band
        if lo <= e["rsi"] <= hi:
            score += 1
            reasons.append(f"RSI {e['rsi']:.0f} in momentum band")
        if rvol_ok:
            score += 1
            reasons.append(f"Volume {e['rvol']:.1f}x average")
        if atr_expanding:
            reasons.append("ATR expanding")  # volatility gate, no extra point

        if not atr_expanding or score < strat.min_confidence:
            continue

        entry = float(e["close"])
        stop = entry - risk.atr_stop_mult * atr_now if long else entry + risk.atr_stop_mult * atr_now
        r_dist = abs(entry - stop)
        targets = [
            (f"TP{i+1}", entry + m * r_dist if long else entry - m * r_dist, m)
            for i, m in enumerate(risk.target_r_multiples)
        ]
        return Signal(
            market="CRYPTO", symbol=symbol, direction=direction,
            exec_tf=exec_tf, bias_tf=bias_tf, entry=entry, stop=float(stop),
            targets=targets, atr=float(atr_now), confidence=score, reasons=reasons,
        )
    return None
