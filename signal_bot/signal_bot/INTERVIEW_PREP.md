# Signal Bot — Technical Interview Prep

Everything you need to defend this project in a technical interview, plus a
categorised question bank with answer pointers.

> **Golden rule:** interviewers probe whatever you claim. Only claim what you can
> derive on a whiteboard. The high-risk areas to truly internalise (not memorise)
> are: lookahead-bias prevention, the indicator math, and *why* there are two
> engines. If you used AI assistance to build parts, that's normal — but you must
> be able to re-explain and re-derive every piece yourself.

---

## 1. The pitches

**One-liner:** "A 24/7 Python service that ingests live crypto and forex market
data, runs two separate rule-based strategy engines to detect intraday trade
setups, and alerts me on Telegram — backed by a walk-forward backtester that
validates the strategies on historical data without lookahead bias."

**30-second version:** "It polls market data on a schedule, computes technical
indicators, and scores each setup against a rule set. Crypto and forex have
genuinely different microstructure, so they get separate engines. Every signal
comes with entry, ATR-based stop, R-multiple targets, and position sizing. The
same engines run inside a backtester so I can measure expectancy and drawdown
before risking anything. It's decision-support — it never places orders."

**What it is NOT (say this proactively if asked about ML/profitability):**
"It's deterministic rules, not machine learning, and I don't claim it's
profitable — the deliverable is correct engineering plus an honest validation
framework. Proving an edge needs out-of-sample testing and better forex data."

---

## 2. How to frame it for DevOps / MLOps roles

Lead with the systems story, not the trading story:

- **Reliability:** a long-running service where one bad symbol or API hiccup must
  not crash the loop (per-symbol exception isolation + an outer try/except).
- **Config & secrets:** all tunables in one config layer; secrets via `.env` /
  environment variables, never in code.
- **Separation of concerns:** data feeds, indicators, strategy logic, risk,
  alerting, and orchestration are independent modules — the strategy doesn't know
  or care where candles come from.
- **Observability:** structured logging to file + console.
- **Deployability:** designed to run under systemd/Docker with a restart policy
  on a small VPS.
- **Validation discipline (the MLOps parallel):** the backtester is to this what
  offline evaluation is to a model — same code path, train/test discipline,
  metrics before deployment. You can explicitly draw the analogy: "backtest =
  offline eval, paper trading = shadow deployment, going live = production."

---

## 3. Architecture & data flow

```
main.py            # entrypoint: logging, build objects, infinite poll loop
  └─ engine.py     # orchestrator: scan loop, session gate, dedup, dispatch
       ├─ datafeeds/crypto.py   # ccxt public OHLCV (no keys, no trading)
       ├─ datafeeds/forex.py    # Twelve Data REST (free key), pluggable
       ├─ indicators.py         # EMA / RSI / ATR / RVOL / session VWAP
       ├─ strategies/
       │    ├─ base.py              # Signal dataclass + Telegram formatting
       │    ├─ crypto_momentum.py   # crypto engine (24/7, VWAP)
       │    └─ forex_session.py     # forex engine (session-gated)
       ├─ risk.py               # fixed-fractional position sizing
       └─ alerts/telegram.py    # Telegram Bot API sender
config.py          # all parameters (dataclasses, env-backed secrets)
backtest.py        # walk-forward validation reusing the engines
```

**Runtime data flow (one scan cycle):**
1. Loop wakes every `poll_seconds` (default 300s).
2. For each symbol, fetch **two** timeframes: a higher-TF *bias* set and a
   lower-TF *execution* set.
3. `enrich()` attaches all indicator columns.
4. The market's engine evaluates the **last closed** candle and returns a
   `Signal` or `None`.
5. Risk module fills in suggested position size.
6. Dedup check (cooldown per symbol+direction) → if new, send Telegram.

**Key invariant:** signals fire on *closed* candles only — the feeds drop the
still-forming last candle (`.iloc[:-1]`).

---

## 4. Design decisions & rationale (your "why" bank)

| Decision | Why |
|---|---|
| **Two separate engines** | Crypto trades 24/7 with real volume and no sessions; forex has sessions, weekend gaps, news sensitivity, and only *tick* volume. Reusing crypto's volume-weighted logic on forex would key off a meaningless signal. |
| **Higher-TF bias + lower-TF entry** | Standard multi-timeframe approach: trade in the direction of the larger trend, time entries on the smaller one — filters counter-trend noise. |
| **Rule-based, not ML** | Interpretable (every signal lists *why* it fired), no training data or overfitting risk, easy to debug and backtest faithfully. ML would add a label-leakage and data-pipeline burden for unclear gain at this scope. |
| **ATR-based stops, R-multiple targets** | Stops adapt to current volatility instead of a fixed distance; thinking in R (risk units) makes expectancy and sizing math clean and market-agnostic. |
| **Fixed-fractional sizing (1%)** | Caps per-trade loss as a % of equity; standard risk control that bounds drawdown. |
| **Confidence score (0–6) + threshold** | Turns "did all conditions align?" into a tunable knob; reduces alert spam and lets you trade only high-conviction setups. |
| **Pluggable data layer** | Strategies depend on a DataFrame contract, not a vendor. Swapping Twelve Data → OANDA is one new class implementing `get_ohlcv()`. |
| **Indicators computed once, then sliced (backtest)** | EMA/RSI/ATR/VWAP are *causal* (value at bar *i* depends only on bars ≤ *i*), so full-series computation then slicing is identical to recomputing each step — but far faster. |
| **Secrets in `.env`** | Keeps tokens out of source control; 12-factor style. |
| **Per-symbol exception isolation** | A single API error or bad symbol logs and continues; it can't take down the whole service. |
| **In-memory dedup with cooldown** | Simple, good enough for a single instance. *Known limitation:* state is lost on restart (a real gap — see §7). |

---

## 5. Deep-dive cheat sheets

### 5a. Indicator math (be ready to derive these)

- **EMA:** `series.ewm(span=n, adjust=False).mean()`. `adjust=False` gives the
  recursive form `EMA_t = α·price_t + (1−α)·EMA_{t−1}` with `α = 2/(n+1)` — the
  standard trading EMA, and the only form that's truly causal/streamable.
- **RSI (Wilder):** `RSI = 100 − 100/(1+RS)`, `RS = avgGain/avgLoss`. Gains/losses
  smoothed with Wilder's method, implemented as `ewm(alpha=1/n, adjust=False)`.
  Guard against divide-by-zero when `avgLoss = 0`.
- **ATR (Wilder):** average of True Range, where
  `TR = max(high−low, |high−prevClose|, |low−prevClose|)`. Captures gaps, unlike
  plain high−low.
- **RVOL:** `volume / rolling_mean(volume, n)` — current bar vs its recent norm.
- **Session VWAP:** typical price `(H+L+C)/3`, then `Σ(price·vol)/Σ(vol)`
  **reset each UTC day** via `groupby(index.normalize())`. Needs real volume →
  meaningful for crypto, returns NaN for volume-less forex.

### 5b. The crypto engine (long; short is the mirror)

1. **Bias (1h):** price above 200 EMA.
2. **Trend (5m):** 20 EMA above 50 EMA; price on the bull side of session VWAP.
3. **Trigger:** pullback to ~20 EMA (within 0.5·ATR) then a bullish reclaim
   candle, **or** a breakout above the N-bar high.
4. **Confirm:** RSI in a momentum band (not exhausted), RVOL above threshold,
   ATR expanding (avoids dead chop).
5. Each block adds to a 0–6 score; only ≥ `min_confidence` alerts. Stop =
   entry ∓ 1.2·ATR; targets at 1R/2R/3R.

### 5c. The forex engine — what's different

- **Session gate:** only fires Mon–Fri inside 07:00–16:00 UTC (London + NY
  overlap), where liquidity and follow-through are highest.
- **Bias** uses 200 EMA **and** RSI on H1.
- **Trigger** requires a pullback-reclaim **plus** breaking the prior minor
  swing (structure), the cleaner FX day-trade pattern.
- **Volume is optional** — tick volume is used only if present, never required.

### 5d. Backtester methodology (the rigor showcase)

- **Walk-forward:** iterate bar by bar; at each step pass the engine only the
  candles closed by then.
- **No lookahead — five guards:**
  1. Indicators are causal (see §4).
  2. Bias bars filtered by **close time, not open time** (`index + duration`),
     found with `searchsorted` for O(log n) lookup — so a still-forming higher-TF
     bar is never visible.
  3. Trades are simulated only on bars *after* the signal bar.
  4. Breakeven arms based on prior bars, never the current bar (no optimism).
  5. Conservative intrabar fills: if a bar's range contains both stop and target,
     the **stop** is assumed hit first.
- **Costs modelled:** entry slippage + round-trip fees (crypto) / spread (forex),
  expressed in R and subtracted from each trade.
- **Sizing/compounding:** `equity *= (1 + risk_pct · realized_R)`.
- **Metrics:** win rate, **expectancy (R/trade)** ← the headline number, profit
  factor, total return, **max drawdown**, longest losing streak, per-symbol
  breakdown.
- **One position per symbol at a time** — can't stack a setup you're already in.

---

## 6. The number that matters

If asked "is it good?": **expectancy in R** is the edge per trade in risk units.
Positive expectancy with a drawdown and losing streak you can stomach beats a
high win rate every time (you can win 70% and still lose money if losers are
big). Profit factor > ~1.3–1.5 supports it. And always qualify: a single backtest
slice is in-sample until proven on data you never tuned on.

---

## 7. Known limitations & "what I'd do next" (rehearse these)

Volunteering weaknesses signals seniority. Have crisp answers:

- **No unit tests yet** → add tests for indicators against known reference values,
  plus the backtest as an integration test.
- **In-memory dedup state** → lost on restart; persist to SQLite/Redis so a
  restart doesn't re-alert or re-enter.
- **Free forex data** → delayed, tick-volume only, doesn't capture spread
  widening on news; swap to OANDA v20 real-time and add an economic-calendar
  blackout.
- **Polling, not streaming** → fine at minute cadence; for faster signals move to
  websockets and event-driven evaluation.
- **Parameters not yet validated out-of-sample** → build a train/test split +
  walk-forward optimisation harness; current thresholds are sensible defaults,
  not proven.
- **Single instance / no HA** → for production, containerise with restart policy,
  add a health check / dead-man's switch that alerts if the bot itself dies.
- **No real execution** → by design; if automated, that's a separate, carefully
  permissioned order-management component with its own kill switch.

---

## 8. Interview question bank

For each: *what they're testing* → *answer pointer*.

### A. Framing
1. **Walk me through this project.** → Structure: problem → architecture → a
   design decision you're proud of (lookahead handling) → a limitation → next
   step. Don't narrate every file.
2. **What was the hardest part?** → Preventing lookahead bias in the backtester;
   explain the close-time bias filtering.
3. **Why did you build it?** → Interest in markets + wanting a real always-on
   service to practise reliability, data ingestion, and validation discipline.
4. **Is it making money?** → The honest, mature answer in §1 / §6.

### B. Trading domain
5. **Why separate crypto and forex engines?** → §4 row 1.
6. **What's VWAP and why crypto-only?** → Volume-weighted average price, resets
   daily; needs real volume, which spot FX lacks (only tick volume).
7. **Why an ATR-based stop instead of fixed pips/%?** → Adapts to volatility;
   same setup gets a wider stop in a volatile regime.
8. **What's "R" and expectancy?** → R = distance to stop = 1 unit of risk;
   expectancy = mean R per trade = your edge.
9. **Why trade only the London/NY session for forex?** → Peak liquidity and
   follow-through; off-session moves are thin and noisy.
10. **What's the risk of curve-fitting your rules?** → Over-tuning to one slice;
    mitigate with out-of-sample/walk-forward testing and few parameters.

### C. Architecture & design
11. **How would you add a third market (e.g. stocks)?** → New data feed
    implementing `get_ohlcv()` + a new engine; orchestrator and indicators reused.
12. **How are concerns separated?** → §3; strategies depend on a DataFrame
    contract, not a vendor.
13. **Why config in dataclasses?** → Typed, discoverable, defaults in one place,
    env-overridable for secrets.
14. **How do you avoid alert spam?** → Confidence threshold + per-symbol/direction
    cooldown dedup.
15. **What's the contract between layers?** → Feeds return a UTC-indexed OHLCV
    DataFrame; engines return a `Signal` or `None`; alerting takes a formatted
    string.

### D. Python & implementation
16. **Why `ewm(adjust=False)`?** → Recursive causal EMA, the standard trading
    form; `adjust=True` would use all history with different weights and isn't
    streamable.
17. **How does the RSI handle divide-by-zero?** → Replace zero average-loss with
    NaN before dividing, then fill.
18. **Why `searchsorted` in the backtest?** → O(log n) lookup of how many bias
    bars have closed, instead of an O(n) boolean mask each step.
19. **How do you keep the 24/7 loop alive?** → Per-symbol try/except + an outer
    try/except around the whole scan; log and continue.
20. **How are secrets handled?** → `python-dotenv` + environment variables;
    `.env` git-ignored, `.env.example` committed.
21. **Why drop the last candle?** → It's still forming; acting on it would mean
    trading incomplete information (a live form of lookahead).

### E. Data & numerical correctness
22. **What if the API returns partial/empty data?** → Raise/skip that symbol,
    log, continue; never feed garbage to the engine.
23. **Timezones?** → Everything UTC end to end; VWAP and forex sessions depend on
    it.
24. **How do you resample to the bias timeframe?** → pandas `resample` with
    open=first, high=max, low=min, close=last, volume=sum; `label/closed='left'`
    to match the open-timestamp convention.
25. **Floating-point / precision concerns?** → Fine for signals; real order sizing
    would need the exchange's tick/lot precision.

### F. Backtesting & validation (expect the deepest probing here)
26. **How do you prevent lookahead bias?** → The five guards in §5d. This is the
    single most important answer in the whole interview.
27. **Why is computing indicators once then slicing valid?** → Causality (§4).
28. **How do you model costs?** → Slippage + fees/spread in R, subtracted per
    trade.
29. **Both stop and target inside one bar — what do you assume?** → Stop first
    (conservative; avoids inflating results).
30. **In-sample vs out-of-sample — what's your plan?** → Tune on older data, test
    once on an untouched recent slice, then paper-trade.
31. **Why is a high win rate not enough?** → §6.
32. **What does the backtest *not* capture?** → News spread-widening on free FX
    data, partial fills, latency, liquidity limits, regime change.

### G. Reliability & DevOps/MLOps
33. **How would you deploy this 24/7?** → Docker + restart policy or a systemd
    service on a VPS; logs shipped out; secrets injected via env.
34. **How do you know the bot is alive?** → *Honest gap today* → add a heartbeat /
    dead-man's switch that alerts if no scan completes within N minutes.
35. **What happens on restart?** → Dedup state is lost (limitation) → persist it.
36. **How would you add CI/CD?** → Lint + unit tests on push, build/publish the
    image, deploy on tag; (ties to your Azure DevOps / GitHub Actions experience).
37. **What's the MLOps analogy if this became ML?** → Backtest = offline eval,
    paper trading = shadow/canary, live = production; you'd need feature stores,
    model versioning, drift monitoring (Evidently-style), and retraining triggers.
38. **How would you monitor strategy decay?** → Track live vs backtested
    expectancy; alert when realised performance drifts from expectation.

### H. Scaling & system design
39. **It now watches 3 symbols. Scale to 500.** → Move from sequential polling to
    async/concurrent fetches or websockets; decouple ingestion from evaluation via
    a queue; persist candles; shard symbols across workers; centralise rate-limit
    handling.
40. **Polling vs streaming — trade-offs?** → Polling is simple and rate-limit
    friendly but adds latency; websockets are real-time but need reconnection and
    backpressure handling.
41. **Where's the bottleneck?** → Network I/O and API rate limits, not CPU; hence
    async over threads, and caching/persistence.

### I. Critical thinking / gotchas
42. **Convince me this isn't overfit.** → Few parameters, economically-motivated
    rules (not data-mined), and a planned out-of-sample test; admit it's unproven
    until then.
43. **A senior trader says technical indicators don't work. Response?** → Stay
    humble: indicators are lagging summaries, not magic; the edge (if any) is in
    risk management and consistency, which is why the framework emphasises R and
    expectancy over prediction.
44. **What would you remove if you rebuilt it?** → Maybe collapse some near-
    duplicate logic between engines into shared helpers while keeping the rules
    distinct; add tests first.
45. **What part are you least confident in?** → Pick something real (e.g. forex
    data quality) and show you understand *why* — far better than feigning mastery.

---

## 9. Final checklist before the interview

- [ ] I can derive EMA, RSI, ATR, and VWAP from scratch.
- [ ] I can explain the five lookahead guards without notes.
- [ ] I can justify two engines with concrete microstructure differences.
- [ ] I can state the project's top 3 limitations and the fix for each.
- [ ] I can give the honest "is it profitable?" answer without flinching.
- [ ] I can draw the architecture/data-flow on a whiteboard in 60 seconds.
- [ ] I never call it "AI" unless I'm describing a future ML extension.
```
