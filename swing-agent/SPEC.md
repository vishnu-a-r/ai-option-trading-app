# Claude Code Brief — Nifty 500 Swing Momentum Agent

## Role

You are building a **signal-generation system**, not an execution bot. It screens the Nifty 500, ranks swing candidates on both sides, and emits a daily actionable shortlist with entry, stop-loss, and target. Order placement stays manual for now (see Compliance).

Build it as a Python project with git version control. Deterministic logic in code; LLM calls only for the qualitative fundamental layer.

---

## 1. Universe & Hard Constraints

- **Base universe:** Nifty 500 constituents (fetch current list, don't hardcode — it rebalances).
- **Long candidates:** full Nifty 500. This is the only side traded — see Section 4.
- Exclude: stocks in ASM/GSM surveillance frameworks, T2T segment, circuit-locked names, and anything with 20-day average traded value below a configurable floor (default ₹10 crore).

---

## 2. Data Sources

**Confirm what's reachable before writing collection code. Report back on each:**

| Need | Candidate source | Status |
|---|---|---|
| OHLCV daily/weekly, Nifty 500 | NSE public endpoints / broker historical API | verify |
| Technical screening | Chartink scan (existing scans available) | verify |
| Fundamentals — ratios, growth, debt | Screener.in, FMP connector | verify India coverage |
| Quarterly results & concall transcripts | BSE/NSE filings | verify |
| FII/DII daily flow | NSE daily reports | verify |
| Shareholding pattern trend (promoter/FII/DII/MF, QoQ) | BSE filings, Trendlyne | verify |
| Bulk & block deals | NSE/BSE daily | verify |
| Stock futures OI, basis, rollover | NSE F&O bhavcopy | verify |
| Delivery percentage | NSE daily | verify |

**Report explicitly:** which of these you can get reliably and free, which need a paid tier, and which have no good source. Do not silently substitute a worse source. If a paid data subscription would materially improve the system, name the service, the cost, and exactly what it unlocks — I'll decide.

---

## 3. Long Setup — Momentum Pullback

Primary filter (all must hold):

- Price above 50-day SMA
- Structure of higher highs and higher lows on the daily chart (define programmatically via swing pivots, don't eyeball)
- RSI(14) between 30 and 60 — i.e. pulled back but not broken
- Broader trend intact: 50 DMA above 200 DMA

Confirmation layer (score, don't gate):

- Stochastic turning up from oversold
- MACD histogram contracting toward a bullish cross
- Volume dry-up on the pullback, expansion on the reversal candle
- Price holding above anchored VWAP measured from the last significant swing low (note: standard session VWAP is an intraday tool — use anchored VWAP for swing context)
- Weekly/monthly CPR: price above the central pivot, narrow CPR indicating a trending expectation (daily CPR is intraday-oriented — use higher timeframe here)
- Relative strength vs Nifty 500 index over 1M/3M

## 4. Short Setup — DROPPED

**Decision, 2026-08-25: this system is long-only.** The short screen, the short
fundamental flags, and the F&O-only short universe are removed from the spec and from
the code. `src/screens/short_breakdown.py` is deleted; `strategy.yaml` has no
`short_breakdown` block, no `fundamental.short_flag`, and no `scoring.top_n_short`.

This is a decision, not unfinished work. Do not reintroduce a short screen — and in
particular do not add one by inverting the long screen, which is what the original
spec warned against: inverting it surfaces strong companies in temporary pullbacks,
the worst possible short.

Consequences elsewhere: every position is now cash equity held long, so exposure is
simply qty × price, and the F&O list is no longer a universe filter — it only marks
where futures confirmation is *available* (Section 7).

## 5. Fundamental Screen

Applied to longs as a gate.

- Sales and profit growth (3Y and TTM), consistency of growth
- ROE / ROCE thresholds
- Debt-to-equity, interest coverage
- Operating cash flow vs reported profit (quality of earnings)
- Promoter holding trend and pledge percentage
- Valuation sanity: PE vs its own 5Y median and vs sector median
- Sector-adjusted where needed — banking and NBFC metrics differ from manufacturing; do not apply one threshold set across all sectors

Output a fundamental score per stock (0–100) with the component breakdown visible, not a black box.

---

## 6. Institutional & Flow Layer

- QoQ change in FII, DII, and mutual fund holding — rising institutional ownership as a long tailwind, falling as a short tailwind
- Bulk/block deal activity in the last 90 days, with counterparty where disclosed
- Delivery percentage trend vs its own 30-day average (accumulation signal)
- Aggregate FII/DII daily flow as a market-regime input, not a stock-level signal

## 7. Futures Layer (F&O stocks only)

- Open interest trend alongside price: rising price + rising OI = long buildup; falling price + rising OI = short buildup
- Futures basis (premium/discount to spot)
- Rollover percentage and cost near expiry
- Where a stock has futures, use this to confirm or veto the cash-market signal

---

## 8. Scoring, Ranking, Output

Composite score with configurable weights across: technical setup quality, fundamental score, institutional flow, futures confirmation, relative strength. Weights live in a config file so they can be tuned without touching logic.

**Daily output** (JSON + a readable summary):

- Top N long candidates, top N short candidates
- For each: entry trigger price, stop-loss level, target(s), risk-reward ratio, position size, and a one-line reason
- Score breakdown so I can see *why* it ranked where it did
- Signals that were close but failed, with the specific failing condition

---

## 9. Risk Management

- Stop-loss placement: below the pullback swing low, with an ATR-based buffer
- Position sizing derived from fixed fractional risk per trade — port the exact sizing formula from my existing Excel swing system rather than inventing one; ask me for it
- Portfolio-level caps: max concurrent positions, max exposure to a single sector, max aggregate open risk
- Exit rules: initial target, trailing logic, and a time-based exit if the setup goes nowhere

---

## 10. Backtest Before Anything Else

Do not hand me live signals from an unvalidated system. Backtest over at least 5 years including 2020 and the 2022 drawdown. Report win rate, average R multiple, max drawdown, longest losing streak, and performance separated by market regime (trending vs range-bound). Be honest about survivorship bias from using the *current* Nifty 500 list on historical data, and correct for it if the data allows.

---

## 11. Compliance Boundary

Since 1 April 2026, SEBI's retail algo framework is fully in force: any order placed by an algorithm needs an exchange-issued Algo-ID, must route through the broker's registered infrastructure, and requires static IP whitelisting. Self-written API strategies are covered, not exempt.

**Therefore: this system generates signals and alerts only.** No order placement, no auto square-off, no programmatic stop-loss submission. Output goes to a file and a notification; I place orders manually or via broker GTT/bracket orders. Do not add execution code unless I explicitly ask and confirm the compliance path with my broker.

---

## 12. Before You Build — Answer These

1. Which data sources from Section 2 can you actually reach? Where are the gaps?
2. What would a paid subscription buy that free sources can't, and is it worth it?
3. Any part of the strategy spec above that is ambiguous or unimplementable as written?
4. Proposed project structure and the order you'd build in.

Start with data availability. Don't write strategy code until the data foundation is confirmed.
