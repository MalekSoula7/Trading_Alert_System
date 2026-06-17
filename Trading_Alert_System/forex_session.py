"""
FOREX engine — session-aware EMA pullback / structure break.

Distinct from crypto: forex runs on sessions, has no true volume, and reacts
hard to scheduled news. So this engine:
  - only ever fires inside the configured UTC session window (set by the engine)
  - uses 200 EMA + RSI for H1 bias
  - triggers on a 20-EMA pullback-and-reclaim that also breaks the prior minor
    swing (structure), the cleanest forex day-trade pattern
  - treats volume as optional confirmation (tick volume if present, else skipped)

Long shown; short is the mirror.
"""
from __future__ import annotations

from typing import Optional
import pandas as pd

from .base import Signal


def analyze_forex(symbol, df_exec, df_bias, strat, risk, exec_tf, bias_tf,
                  session_label) -> Optional[Signal]:
    e = df_exec.iloc[-1]
    prev = df_exec.iloc[-2]
    b = df_bias.iloc[-1]

    atr_now = e["atr"]
    if pd.isna(atr_now) or atr_now == 0:
        return None
    atr_avg = df_exec["atr"].rolling(strat.rvol_period).mean().iloc[-1]
    atr_expanding = atr_now >= atr_avg

    swing_high = df_exec["high"].iloc[-(strat.breakout_lookback + 1):-1].max()
    swing_low = df_exec["low"].iloc[-(strat.breakout_lookback + 1):-1].min()
    has_volume = df_exec["volume"].fillna(0).sum() > 0

    for direction in ("LONG", "SHORT"):
        long = direction == "LONG"
        reasons, score = [], 0

        # --- H1 BIAS: 200 EMA + RSI ------------------------------------
        bias_ema = b["close"] > b["ema_trend"] if long else b["close"] < b["ema_trend"]
        bias_rsi = (b["rsi"] >= 50) if long else (b["rsi"] <= 50)
        if not (bias_ema and bias_rsi):
            continue
        score += 1
        reasons.append(f"{bias_tf} bias: price {'above' if long else 'below'} 200 EMA, RSI {b['rsi']:.0f}")

        # --- EMA stack on exec TF --------------------------------------
        stack_ok = e["ema_fast"] > e["ema_slow"] if long else e["ema_fast"] < e["ema_slow"]
        if not stack_ok:
            continue
        score += 1
        reasons.append(f"{exec_tf} 20/50 EMA aligned {'up' if long else 'down'}")

        # --- TRIGGER: pullback to 20 EMA + reclaim + structure break ---
        near_ema = abs(prev["low" if long else "high"] - prev["ema_fast"]) <= strat.pullback_atr * atr_now
        reclaim = (e["close"] > e["ema_fast"] and e["close"] > e["open"]) if long \
            else (e["close"] < e["ema_fast"] and e["close"] < e["open"])
        structure = e["close"] > swing_high if long else e["close"] < swing_low
        if not (near_ema and reclaim):
            continue
        score += 1
        reasons.append("Pullback to 20 EMA + reclaim candle")
        if structure:
            score += 1
            reasons.append("Broke prior minor swing")

        # --- CONFIRM ----------------------------------------------------
        lo, hi = strat.rsi_long_band if long else strat.rsi_short_band
        if lo <= e["rsi"] <= hi:
            score += 1
            reasons.append(f"{exec_tf} RSI {e['rsi']:.0f} in momentum band")
        if has_volume and not pd.isna(e["rvol"]) and e["rvol"] >= strat.rvol_min:
            score += 1
            reasons.append(f"Tick volume {e['rvol']:.1f}x average")
        if atr_expanding:
            reasons.append("ATR expanding")

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
            market="FOREX", symbol=symbol, direction=direction,
            exec_tf=exec_tf, bias_tf=bias_tf, entry=entry, stop=float(stop),
            targets=targets, atr=float(atr_now), confidence=score, reasons=reasons,
            session=session_label,
        )
    return None
