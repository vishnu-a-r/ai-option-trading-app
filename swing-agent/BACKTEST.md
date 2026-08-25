# Backtest results

**Date:** 2026-08-25 · **Verdict: the strategy as specified does not work.**
Run `python scripts/run_backtest.py` to reproduce. Transaction costs are modelled.

---

## Full Nifty 500 — the result that counts

463 usable symbols (37 excluded by bar quality and corporate actions),
2020-06-01 → 2026-08-21, **651 trades, costs modelled, prices split-adjusted**:

```
win rate               37.9%
average R (net)        -0.059
  gross                -0.005
  cost drag            0.055 R/trade
max drawdown           68.8%
longest losing streak  21
exits                  stop=210, stop_gap=32, time_stop=409

  trending      trades=176   win=46.6%   avgR=+0.080
  range_bound   trades=465   win=34.6%   avgR=-0.109
```

**A 68.8% drawdown and 21 consecutive losers are not survivable.** Not as ruin —
sizing caps that — but nobody follows a system through it.

### Adjusting for splits changed the answer

The run before this one used unadjusted prices, in which 105 of 500 symbols carried
at least one split or bonus that every indicator read as a 50-80% crash:

| | unadjusted | split-adjusted |
|---|---|---|
| average R (net) | −0.111 | **−0.059** |
| average R (gross) | −0.055 | **−0.005** |
| max drawdown | 59.1% | **68.8%** |
| trending avg R | −0.155 | **+0.080** |
| range-bound avg R | −0.101 | −0.109 |

Net R nearly halved and the trending bucket flipped sign. Drawdown got *worse*. The
direction was not predictable in advance, which is the argument for fixing data before
tuning anything: a refinement developed on the unadjusted series would have been fitted
to artifacts, and there is no way to tell from the inside which numbers those were.

**Still losing.** Gross is now roughly flat (−0.005) and costs alone push it negative.

### The regime split, again — and why it is still not an instruction

Trending now reads **+0.080 on 176 trades**, against range-bound −0.109 on 465. That
is the same shape as the 13-name result recorded below, which did not replicate — but
on a sample four times larger and on corrected data.

That makes it worth *testing*. It does not make it a finding. The earlier version of
this document treated a 39-trade split as an instruction and was wrong. The difference
between a hypothesis and a result is out-of-sample validation, which has not been done:
develop on 2020–2023, verify on 2024–2026 held out. Until then a regime filter is a
plausible idea, not a change to make.

Note also that +0.080 net R is thin. Even if it survives out-of-sample, a system that
trades only in trending regimes takes roughly a quarter of the signals for a payoff
barely above zero after costs.

## The 13-name regime conclusion, kept as a warning

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

## Now modelled (2)

- **Corporate actions** — splits and bonuses are back-adjusted from the price series,
  since NSE publishes no corporate-actions file. Symbols whose event matches no clean
  split ratio, or whose "event" spans a gap in the data, are refused rather than
  adjusted by the nearest guess: 90 adjusted, 15 refused.

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
