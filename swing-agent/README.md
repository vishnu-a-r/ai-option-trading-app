# Nifty 500 Swing Momentum Agent — skeleton

Mostly scaffolding: signatures and intent. Two modules are implemented and
tested — `src/data/quality.py` and `pivots.swing_points()` — because they are
pure functions that need no live data source. Everything else is still stubs.

Read `SPEC.md` first, then **`DATA_AUDIT.md`** — the data foundation is not
confirmed and that is currently the blocker, not the code.

## Build order

1. **Data availability audit** — Section 12 of SPEC.md. Which sources in
   `src/data/` can actually be reached, free vs paid, where the gaps are.
   Report back before implementing anything.
   *Partially done — see `DATA_AUDIT.md`. Result: 70% of the composite score
   has no confirmed source and the price feed reached is on the wrong exchange.
   Resolve NSE access before strategy work.*
2. **Data layer** — implement the Protocols in `src/data/base.py`. Cache to disk.
3. **Indicators** — `src/indicators/`, with tests. `pivots.swing_points()` is the
   foundation for all structure detection; test it before building on it.
4. **Screens** — long first, validate against known historical setups by hand.
5. **Fundamental + institutional layers.**
6. **Scoring and risk.** Port the sizing formula from the existing Excel system —
   do not invent one.
7. **Backtest.** No live signals until this reports honest numbers.
8. **Daily runner and output.**

## Structure

```
config/strategy.yaml     all thresholds and weights — no hardcoded numbers in src/
config/universe.yaml     universe definition and exclusions
src/data/base.py         source Protocols — swap providers without touching strategy
src/indicators/          pure functions on OHLCV
src/screens/             long_pullback, fundamental
src/scoring/composite.py weighted rank across five signal families
src/risk/sizing.py       stops, sizing, portfolio caps
src/backtest/engine.py   5+ years, regime-split, survivorship-aware
src/output/report.py     JSON + readable summary
run_daily.py             orchestration
```

## Two things not to get wrong

**Pivots are not knowable when they print.** `swing_points()` returns a
`confirmed_at_bar` column; the backtest must filter on it rather than on the
pivot's own bar index. Getting this wrong lets the screen see a swing low days
before the market did and flatters every entry price in the run.

**Risk and cash are different constraints.** `max_aggregate_open_risk_pct` caps
what you can lose; `max_deployed_pct_of_capital` caps what you can spend. Six
tight-stop positions can sit well inside the risk cap while asking for 150% of
the account. Both gates have to fire independently.

**Long only.** Shorts were dropped by decision — see SPEC.md section 4. There is
no short screen and no short config, and neither should come back.

## Not in scope

No execution. See the module docstring in `run_daily.py`.
