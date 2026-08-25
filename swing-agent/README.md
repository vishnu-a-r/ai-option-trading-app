# Nifty 500 Swing Momentum Agent — skeleton

The source-independent layer is implemented and tested (191 tests): config
loading and validation, all indicators, bar-quality screening, the long screen,
stops and portfolio gates, and composite ranking. It runs end-to-end on the
committed fixtures in `tests/fixtures/`.

Still stubs, all for the same reason — no data: the fundamental, institutional
and futures screens, `run_daily.main()`, the backtest engine, and `report.py`.
`position_size()` is stubbed for a different reason: it needs the Excel formula
(SPEC §9) and raises rather than guessing.

Read `SPEC.md` first, then **`DATA_AUDIT.md`** — the data foundation is not
confirmed and that is currently the blocker, not the code.

## Build order

1. **Data availability audit** — Section 12 of SPEC.md. Which sources in
   `src/data/` can actually be reached, free vs paid, where the gaps are.
   Report back before implementing anything.
   *Partially done — see `DATA_AUDIT.md`. Result: 70% of the composite score
   has no confirmed source and the price feed reached is on the wrong exchange.
   **Resolving NSE egress is the blocker for everything below step 6.***
2. **Data layer** — implement the Protocols in `src/data/base.py`. Cache to disk.
3. **Indicators** — `src/indicators/`, with tests. ✅ done.
   `pivots.swing_points()` is the foundation for all structure detection.
4. **Screens** — long screen ✅ done against fixtures. Still needs validation
   against known historical setups by hand, which needs real data.
5. **Fundamental + institutional layers.** Blocked: no source.
6. **Scoring and risk.** ✅ except `position_size()` — still needs the sizing
   formula from the existing Excel system. Do not invent one.
7. **Backtest.** No live signals until this reports honest numbers.
8. **Daily runner and output.**

## Structure

```
config/strategy.yaml     all thresholds and weights — no hardcoded numbers in src/
config/universe.yaml     universe definition and exclusions
src/config.py            validating loader; require() guards the deliberate nulls
src/data/quality.py      bar-quality screening between data and indicators
src/data/csv_source.py   CSV-backed PriceSource for development and tests
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
