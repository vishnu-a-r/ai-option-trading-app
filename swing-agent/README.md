# Nifty 500 Swing Momentum Agent — skeleton

Scaffolding only. Every module is signatures and intent; no logic is implemented.
Read `SPEC.md` first, then answer its Section 12 questions before writing code.

## Build order

1. **Data availability audit** — Section 12 of SPEC.md. Which sources in
   `src/data/` can actually be reached, free vs paid, where the gaps are.
   Report back before implementing anything.
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
src/screens/             long_pullback, short_breakdown, fundamental
src/scoring/composite.py weighted rank across five signal families
src/risk/sizing.py       stops, sizing, portfolio caps
src/backtest/engine.py   5+ years, regime-split, survivorship-aware
src/output/report.py     JSON + readable summary
run_daily.py             orchestration
```

## Two things not to get wrong

**Shorts are F&O-only.** Cash equity cannot be held short overnight in India.
The short universe is the stock futures list, not the Nifty 500.

**The short screen is not an inverted long screen.** It needs independently
negative fundamentals. Inverting the long screen surfaces strong companies in
temporary pullbacks — the worst possible short.

## Not in scope

No execution. See the module docstring in `run_daily.py`.
