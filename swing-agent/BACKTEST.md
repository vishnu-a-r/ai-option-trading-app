# Backtest results

**Date:** 2026-08-25 · **Verdict: the strategy as specified does not work.**
Run `python scripts/run_backtest.py` to reproduce. Transaction costs are modelled.

---

## Full Nifty 500 — the result that counts

478 usable symbols (22 excluded by bar quality), 2020-06-01 → 2026-08-21, **644 trades**:

```
win rate               39.6%
average R (net)        -0.111
  gross                -0.055
  cost drag            0.057 R/trade
max drawdown           59.1%
longest losing streak  19
exits                  stop=199, stop_gap=36, time_stop=409

  trending      trades=170   win=44.1%   avgR=-0.155
  range_bound   trades=466   win=37.8%   avgR=-0.101
```

**A 59.1% drawdown and a 19-trade losing streak are not survivable.** Not as ruin —
position sizing caps that — but nobody keeps following a system through nineteen
consecutive losers with the account more than halved.

**Costs changed the verdict, not just the decimal.** The first version of this run
modelled no costs and reported −0.026, which reads as "roughly breakeven, worth
tuning". With costs it is −0.111: a system losing about a ninth of its risked amount
on every trade. The drag of 0.057 R/trade landed at the top of the 0.02–0.06 estimate
made before it was measured. Note gross also moved (−0.026 → −0.055), because slippage
changes fill prices rather than being deducted afterwards, so it alters which trades
happen and at what level.

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

## Now modelled

- **Transaction costs** — brokerage, STT both legs, exchange and SEBI charges, stamp
  duty on the buy, GST on fees, and the per-scrip DP charge on the sell. Itemised
  rather than a flat percentage of turnover, because the DP charge is per scrip and
  therefore falls hardest on small positions, which a percentage model would miss.
  Rates are the common Indian discount-broker structure and should be replaced with
  figures from an actual contract note.
- **Slippage** — 0.05% each side, applied to the fill price rather than as a fee.

## Still not modelled — results remain optimistic

- **Survivorship bias.** Today's Nifty 500 applied across history excludes every name
  that fell out of the index. No point-in-time source found. Biases results *upward*.
- **Liquidity and impact.** Fills are assumed at the open with no market impact.

Both make the reported numbers better than reality, and neither makes them worse.

## What this does NOT say

It does not say momentum pullback trading fails. It says *this configuration* —
these gate thresholds, this stop rule, a 15-bar time stop, no target, no trailing, no
regime filter, no fundamental gate — has no edge on this universe over this window.

Three of those are unset rather than chosen: `fundamental.long_gate` (no data source),
`target_r_multiple`, and `trailing`. The system has never been tested with its
fundamental layer, which carries 0.30 of the intended composite weight.

## Honest next steps

1. ~~Add transaction costs.~~ ✅ Done — and they moved the verdict.
2. **Do not tune thresholds against this number.** With 646 trades and no held-out
   period, anything found by searching parameters is overfitting. Any change needs
   walk-forward or out-of-sample validation.
3. The fundamental layer is the largest untested component. Until FMP Starter or an
   equivalent lands, 30% of the intended signal has never run.

**No live signals.** SPEC §10 gates them on honest numbers, and these are honest and bad.
