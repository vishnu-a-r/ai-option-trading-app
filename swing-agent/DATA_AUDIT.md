# Data Availability Audit — SPEC §12

**Date:** 2026-08-25 · **Status:** partial — blocked, see §5
**Method:** live calls from the Claude Code session environment. Every row marked
TESTED has a call behind it. Rows marked UNTESTED were not reached and are not guessed.

> Read §5 first. Four of the five signal families in `scoring.weights` have no
> confirmed source, so this is not a "mostly fine, some gaps" report.

---

## 1. Source-by-source result

| Need | Source tried | Result | Evidence |
|---|---|---|---|
| OHLCV daily, Nifty 500 | Alpha Vantage | ⚠️ **BSE only** | `RELIANCE.NSE` → `{}`; `RELIANCE.BSE` → 100 daily bars |
| Symbol resolution | Alpha Vantage `SYMBOL_SEARCH` | ⚠️ BSE only | 10 matches for "RELIANCE", every Indian one `.BSE`, zero NSE |
| Symbol resolution | FMP `search-symbol` | ✅ knows NSE | returns `RELIANCE.NS`, `RELIANCE.BO`, currency INR, exchange NSE |
| Quotes | FMP `quote` | ❌ plan-denied | ACCESS DENIED — requires higher tier |
| Ratios (ROE/ROCE/D-E) | FMP `key-metrics` | ❌ plan-denied | ACCESS DENIED |
| Statements (revenue/PAT/OCF) | FMP `statements` | ❌ plan-denied | ACCESS DENIED |
| Company profile + **sector** | FMP `profile-symbol` | ❌ plan-denied | ACCESS DENIED |
| Universe construction | FMP `search-company-screener` | ❌ plan-denied | ACCESS DENIED — tool-level, Starter+ |
| Nifty 500 constituents | `nsearchives.nseindia.com` | ❌ blocked | CONNECT 403 at the egress proxy |
| NSE OHLCV / delivery % / F&O OI / rollover | `nseindia.com` | ❌ blocked | CONNECT 403 at the egress proxy |
| Chartink scans | — | ⬜ UNTESTED | |
| Screener.in | — | ⬜ UNTESTED | no official API; scraping ToS unreviewed |
| BSE/NSE filings, transcripts | — | ⬜ UNTESTED | |
| Shareholding pattern QoQ | — | ⬜ UNTESTED | |
| Bulk & block deals | — | ⬜ UNTESTED | |
| FII/DII daily flow | — | ⬜ UNTESTED | |

---

## 2. Alpha Vantage is BSE-only, and that is a volume problem

The ticker mismatch is the small half. The large half is that `volume` on BSE is a
minority share of a dual-listed name's real turnover — `RELIANCE.BSE` prints on the
order of 10⁵–10⁶ shares/day against NSE's 10⁷. The exact ratio is unmeasured here
because NSE is unreachable (§1), but the split is lopsided and well documented.

Three configured numbers are computed directly off volume and all three break on a
minority-share feed:

- `universe.min_avg_traded_value_cr: 10` — a ₹10 cr floor applied to BSE turnover
  excludes most of the Nifty 500 for being illiquid when it isn't.
- `long_pullback.confirmation.volume_dryup_ratio: 0.7`
- `long_pullback.confirmation.volume_expansion_ratio: 1.5`

Dry-up and expansion are a matched pair in the confirmation layer. On a thin
secondary feed the day-to-day variance is dominated by whether a handful of BSE
participants happened to trade, not by the accumulation the signal is trying to read.

**Verdict:** Alpha Vantage is usable for a price-only smoke test. It is not a
foundation for this strategy. Anything volume-derived built on it will validate
cleanly and mean nothing.

---

## 3. A data-quality defect found in the first 100 bars

```
RELIANCE.BSE  2026-06-26   o=h=l=c=1318.25   volume=0
```

A carried-forward non-trading bar. It propagates:

1. **True Range = 0** → drags `ATR(14)` below the real value → `risk.atr_stop_buffer: 0.5`
   multiplies a corrupted ATR → the stop moves → and the stop is what sizes the
   position. A quiet error in ATR is a quiet error in every rupee figure printed.
2. **20-day average volume understated** → `volume_dryup()` sees contraction that
   isn't there.
3. **`high == low`** makes the bar both a swing-high and a swing-low candidate,
   putting noise into the structure detection everything else rests on.

Addressed in this branch — see §6. Note this defect is **not** Alpha-Vantage-specific;
NSE bhavcopy carries suspended and non-traded scrips too. The guard is worth keeping
whatever the source turns out to be.

---

## 4. FMP on the current plan

Only `search-symbol` responds. It does confirm FMP carries NSE symbology
(`RELIANCE.NS`, INR, "National Stock Exchange of India"), so India coverage exists at
higher tiers — but on this plan FMP delivers **no fundamental data at all**.

Two consequences beyond the obvious:

- `fundamental.long_gate` thresholds cannot be calibrated. They stay `null`. A guessed
  ROCE/D-E threshold would silently filter the universe and every backtest number
  downstream would inherit it with no record of where it came from.
- `risk.sector_taxonomy` cannot be resolved. `profile-symbol` was the sector-label
  source, and both sector caps in the risk block are unenforceable without one.

---

## 5. What this means for the build

`scoring.weights` against confirmed sources:

| Family | Weight | Source status |
|---|---|---|
| technical_setup | 0.30 | ⚠️ wrong exchange, volume unusable |
| fundamental | 0.30 | ❌ none |
| institutional | 0.20 | ❌ none |
| futures_confirmation | 0.10 | ❌ none |
| relative_strength | 0.10 | ⚠️ needs a Nifty 500 index series — untested |

**70% of the composite has no source and the remaining 30% is on the wrong exchange.**
Per the README build order, strategy code does not start here. The honest answer to
SPEC §12.1 is that the data foundation is not confirmed.

---

## 6. Answers to SPEC §12

**1. Which sources can you actually reach?** See §1. In this environment: symbol
resolution only. Note the NSE 403 is *this environment's egress policy*, not NSE
refusing — the proxy log shows a policy denial at CONNECT, not an upstream failure.
The same requests should work from a machine with open egress.

**2. What would a paid subscription buy?** FMP Starter is the candidate: it unlocks
statements, ratios, and `profile-symbol` (which also supplies the sector label the risk
block needs). Worth a trial *before* paying, and the question to answer on that trial
is not whether the endpoints respond — it is whether **Nifty 500 midcap** depth is
there. Vendor India coverage is typically solid for the top 100 and thins out below,
and the midcaps are where this screen lives.

What no subscription substitutes for: **delivery percentage, stock-futures OI, basis,
and rollover are NSE-published and have no vendor equivalent.** SPEC §6 and §7 —
30% of the composite — depend on NSE access specifically. This is the access to fix
first; it is also free.

**3. Ambiguous or unimplementable as written?** Three, all recorded in
`config/strategy.yaml`:
- Sector caps need a taxonomy pinned before either number means anything
  (`risk.sector_taxonomy`, currently `null`).
- Exposure had to be defined as notional on both sides, which surfaces that at
  ₹2,00,000 capital a single stock-futures lot breaches `max_position_pct_of_capital`
  on its own — **the short side is structurally unfundable at current capital.**
  The screen should still run and report; expect every short refused at that gate.
- SPEC §9 says to port the sizing formula from the existing Excel system. Still
  outstanding — `src/risk/sizing.py` must not be filled in from first principles.

**4. Proposed order.** Unchanged from the README, except that source-independent work
moves ahead of blocked work rather than the build stalling:

1. Resolve NSE access (egress allowlist, or run the data layer locally and commit cached
   bhavcopy). ← the actual blocker
2. FMP Starter trial, checking midcap depth specifically.
3. Meanwhile: indicators, which are pure functions and need no live source. Started
   in this branch — `src/data/quality.py` and `pivots.swing_points()`, 50 tests.
4. Then the build order as written.

---

## 7. Landed in this branch

- `src/data/quality.py` — bar-quality screening between the data and indicator layers.
  Drops corrupt and non-traded bars; **rejects the symbol** rather than silently
  cleaning it when staleness exceeds `data_quality.max_stale_bar_pct`. The §3 bar is a
  verbatim regression test.
- `config/strategy.yaml` — `data_quality` block. Thresholds live in config, per the
  file's own rule.
- `src/indicators/pivots.py` — `swing_points()` implemented, plus `confirmed_as_of()`.
  A fractal pivot is not knowable when it prints; it is confirmed `lookback` bars later.
  `confirmed_at_bar` records that, and **the backtest must filter on it** — filtering on
  the pivot's own bar index lets the screen see a swing low up to `lookback` days before
  the market did, which flatters every entry price in the run.
- `tests/` — 50 tests. Fixtures are hand-built so expected pivots are verifiable by
  reading the series.

## 8. Not done

- Chartink, Screener.in, BSE/NSE filings, shareholding, bulk deals, FII/DII — untested,
  and untested is not the same as unavailable.
- The BSE-vs-NSE volume ratio is asserted from general knowledge, not measured, because
  NSE is unreachable from here. Worth measuring once access exists.
- Corporate actions. `quality.py` cannot detect a split or bonus — it looks like a
  legitimate gap with healthy volume. Use an adjusted series.
- Survivorship bias (SPEC §10). Needs point-in-time Nifty 500 membership; no source
  identified yet, and today's list applied to 2020 data will overstate every result.
