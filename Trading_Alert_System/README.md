# Signal Bot — intraday alert engine (crypto + forex)

A 24/7 Python bot that scans crypto and forex on a day-trading horizon and pings
you on **Telegram** when a high-probability setup appears — with direction,
entry, stop, R-multiple targets, R:R, suggested position size, and *why* it fired.

It is an **alerting / decision-support tool. It does not place trades.** No
broker keys, no order permissions, no money touched.

---

## What it does

Two **separate** engines (you can't run forex logic on crypto, as you said):

| | Crypto engine | Forex engine |
|---|---|---|
| Hours | 24/7 | London + London/NY overlap only (07:00–16:00 UTC, Mon–Fri) |
| Data | ccxt public OHLCV (Binance by default, no key) | Twelve Data REST (free key) |
| Bias | 1h: price vs 200 EMA + session VWAP | 1h: 200 EMA + RSI |
| Entry | 5m: 20/50 EMA stack, pullback-reclaim **or** breakout | 15m: 20/50 EMA stack, pullback-reclaim + swing break |
| Confirm | RSI band, RVOL (volume), ATR expanding | RSI band, tick-volume (if any), ATR expanding |
| Volume | real volume | tick volume only, treated as optional |

Both score each setup **0–6**; only setups at/above `min_confidence` alert. Stops
are ATR-based; targets are 1R/2R/3R; sizing is fixed-fractional (default 1%).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # then fill in your values
python main.py                # runs forever; Ctrl-C to stop
```

**Telegram:** message @BotFather to create a bot (get the token), then message
@userinfobot to get your numeric chat id. Put both in `.env`.

**Forex:** get a free API key at twelvedata.com and set `TWELVEDATA_API_KEY`.
Leave it blank to run **crypto-only** — the bot degrades gracefully.

If Telegram isn't configured, alerts still print to the console/log.

## Running it truly 24/7

Crypto never sleeps, so use a always-on box (a $5/mo VPS, a Raspberry Pi, or a
free-tier cloud VM). Quickest:

```bash
# on the server, inside the project folder
nohup python main.py > out.log 2>&1 &
```

For something sturdier use a `systemd` service or `pm2`. (You've done DevOps —
a tiny Dockerfile + restart policy would be the clean version.)

## Tuning

Everything lives in `config.py`: pairs, timeframes, RSI/EMA/ATR periods, RVOL
threshold, `min_confidence`, poll interval, cooldown, risk %. Start strict
(fewer, better alerts) and loosen only after you've validated.

---

## ⚠️ Read this before you trust a single signal

1. **This predicts nothing.** It flags rule-based setups that *historically*
   tend to precede moves. It will be wrong regularly. Your edge is risk control,
   not the signals.
2. **Backtest first.** None of these thresholds are validated on *your* pairs.
   Before risking money, run the strategy logic over historical data and look at
   win rate, average R, max drawdown, and expectancy. Then forward-test on a
   **demo/paper account** for weeks.
3. **Free forex data is delayed and has no true volume.** Twelve Data intraday
   bars can lag and "volume" is tick count. For anything serious, switch the
   forex feed to OANDA's v20 practice API (real-time, free demo) — the data
   layer is pluggable for exactly this.
4. **News risk.** The forex engine avoids off-hours but not scheduled releases
   (NFP, CPI, FOMC). Add an economic-calendar blackout before going live.
5. **Not financial advice.** I'm a tool, not a licensed advisor. You own every
   decision.

## Suggested next steps
- Add a `backtest.py` that replays historical candles through the same engines.
- Add an economic-calendar feed to blackout forex around high-impact news.
- Swap Twelve Data → OANDA for real-time forex.
- Add a daily-loss-cap state that pauses alerts after a bad day.
