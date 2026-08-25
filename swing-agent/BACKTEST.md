# Backtest results

**Date:** 2026-08-25 · **Verdict: the strategy as specified does not work.**
Run `python scripts/run_backtest.py` to reproduce.

---

## Full Nifty 500 — the result that counts

478 usable symbols (22 excluded by bar quality), 2020-06-01 → 2026-08-21, **646 trades**:

```
win rate               41.8%
average R              -0.026
max drawdown           53.7%
longest losing streak  19
exits                  stop=201, stop_gap=35, time_stop=410

  trending      trades=174   win=45.4%   avgR=-0.090
  range_bound   trades=464   win=40.3%   avgR=-0.008
```

**A 53.7% drawdown and a 19-trade losing streak are not survivable.** Not in the sense
of ruin — position sizing caps that — but in the sense that no one keeps following a
system through nineteen consecutive losers and half the account gone. The average R of
−0.026 is roughly breakeven *before costs*, and costs are not modelled (see below), so
the real figure is worse.

## The regime conclusion did not survive

An earlier run over 13 Financial Services names showed this:

```
  trending      trades=39    win=56.4%   avgR=+0.219      <- looked like the answer
  range_bound   trades=114   win=42.1%   avgR=-0.282
```

That reads as a clear story: the setup works in trends and bleeds in chop, so gate
entries on regime. **It does not replicate.** Across 646 trades the trending bucket is
*worse* than the range-bound one (−0.090 vs −0.008), and both are negative.

Thirty-nine trades was not a sample. The apparent +0.219 was noise, and the fact that
it formed such a tidy narrative is exactly what made it dangerous — it pointed at a
specific, plausible, wrong change. Recorded here rather than deleted, because the
failure mode is worth keeping: a small-sample split that tells a good story is the
easiest way to fit a strategy to nothing.

## What the exit distribution says

`time_stop=410` of 646 — **63% of positions expire rather than resolve.** They neither
reach a stop nor run; they sit for fifteen bars and get closed. That is the direct
consequence of `target_r_multiple` and `trailing` being null: there is no mechanism to
take profit, so winners are handed back at the time stop.

This cuts both ways and should not be used as an excuse. It means the test measures the
*unmanaged* setup and a managed version could be better. It also means 63% of the
system's behaviour is currently governed by a parameter (`time_stop_bars: 15`) that was
never calibrated against anything.

## Not modelled — results are optimistic

- **Transaction costs.** No brokerage, STT, stamp duty, exchange fees, or slippage.
  Indian round-trip costs on delivery equity are on the order of 0.1–0.3% of position
  value. Against a typical ~5% stop distance that is roughly 0.02–0.06 R per trade,
  which on an average R of −0.026 is not a rounding error — it is the same size as the
  result. **Adding costs would move this from "breakeven-ish" to "clearly losing".**
- **Survivorship bias.** Today's Nifty 500 applied across history excludes every name
  that fell out of the index. No point-in-time source found. Biases results *upward*.
- **Liquidity and impact.** Fills are assumed at the open with no market impact.

Every one of these makes the reported numbers better than reality, and none makes them
worse.

## What this does NOT say

It does not say momentum pullback trading fails. It says *this configuration* —
these gate thresholds, this stop rule, a 15-bar time stop, no target, no trailing, no
regime filter, no fundamental gate — has no edge on this universe over this window.

Three of those are unset rather than chosen: `fundamental.long_gate` (no data source),
`target_r_multiple`, and `trailing`. The system has never been tested with its
fundamental layer, which carries 0.30 of the intended composite weight.

## Honest next steps

1. **Add transaction costs** before any further tuning, so the baseline is real.
2. **Do not tune thresholds against this number.** With 646 trades and no held-out
   period, anything found by searching parameters is overfitting. Any change needs
   walk-forward or out-of-sample validation.
3. The fundamental layer is the largest untested component. Until FMP Starter or an
   equivalent lands, 30% of the intended signal has never run.

**No live signals.** SPEC §10 gates them on honest numbers, and these are honest and bad.
