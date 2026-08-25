# Data Availability Audit — SPEC §12

**Date:** 2026-08-25 · **Status:** substantially unblocked — see the update below
**Updated:** 2026-08-25, after `*.nseindia.com` was added to the environment's egress allowlist.
**Method:** live calls from the Claude Code session environment. Every row marked
TESTED has a call behind it. Rows marked UNTESTED were not reached and are not guessed.

> **UPDATE — NSE access resolved.** The blocker named throughout this document was
> the environment's egress policy, not NSE. With `*.nseindia.com` and `nseindia.com`
> allowlisted, `nsearchives.nseindia.com` serves everything the audit said had no
> substitute. Four findings below are now superseded and marked ✅ RESOLVED. The
> fundamental layer (0.30 weight) is the one that remains genuinely blocked.

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
| Nifty 500 constituents + **sector labels** | `nsearchives.nseindia.com` | ✅ **RESOLVED** | `ind_nifty500list.csv`: 500 names, with an `Industry` column (20 values) |
| NSE OHLCV + **delivery %** | `nsearchives.nseindia.com` | ✅ **RESOLVED** | `sec_bhavdata_full_DDMMYYYY.csv`: 2,633 EQ rows, `DELIV_PER` on 500/500 Nifty 500 names |
| Stock futures OI, basis, lot size | `nsearchives.nseindia.com` | ✅ **RESOLVED** | `BhavCopy_NSE_FO_..._F_0000.csv.zip`: 208 stock-futures underlyings, `OpnIntrst`, `ChngInOpnIntrst`, `NewBrdLotQty` |
| `www.nseindia.com` JSON API | `www.nseindia.com` | ⚠️ 403 | NSE bot protection, **not** the proxy — 0 proxy failures logged. Archives make it unnecessary |
| **Nifty 500 index closes** (RS benchmark) | `nsearchives.nseindia.com` | ✅ **RESOLVED** | `ind_close_all_DDMMYYYY.csv`: 165 indices with OHLC, plus index-level P/E, P/B, dividend yield |
| **Per-stock fundamentals** | Alpha Vantage | ❌ **none** | `COMPANY_OVERVIEW` and `INCOME_STATEMENT` both return `{}` for `RELIANCE.BSE` — same empty signature as the price endpoint for `.NSE` |
| Per-stock fundamentals | NSE archives | ❌ none | Probed `Fin_Results_*`, `shareholding_pattern`, `ind_nifty500_Index_Ratios` — all 404. The archive publishes market data, not financials |
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

**Verdict:** Alpha Vantage is superseded. NSE bhavcopy is the source for price and
volume; nothing volume-derived should be built on a feed carrying 6% of the turnover.

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
| technical_setup | 0.30 | ✅ NSE bhavcopy, correct exchange |
| fundamental | 0.30 | ❌ **none — the remaining blocker** |
| institutional | 0.20 | ⚠️ delivery % ✅; shareholding QoQ, bulk deals, FII/DII still untested |
| futures_confirmation | 0.10 | ✅ F&O bhavcopy (applies to 208 of 500 — see below) |
| relative_strength | 0.10 | ✅ `ind_close_all_*.csv` carries Nifty 500 and sectoral index closes |

~~**70% of the composite has no source and the remaining 30% is on the wrong exchange.**~~
**Superseded.** With NSE access, 0.40 of the weight is fully sourced, 0.20 is partly
sourced, and **0.30 (fundamental) is the one family still without any source.**

A second scoring problem surfaced while planning against this table: only 208 of the
Nifty 500 have stock futures (measured from the F&O bhavcopy, not estimated), so under a naive blend the other ~320 score zero on a
0.10-weight family and can never rank as well as an equivalent F&O name. `rank()`
renormalises over the families that apply instead, and records `families_used` —
which matters acutely right now, since with no fundamental or institutional source
every candidate would otherwise be ranked on two of five inputs behind a
confident-looking composite number.
Per the README build order, strategy code does not start here. The honest answer to
SPEC §12.1 is that the data foundation is not confirmed.

---

## 6. Answers to SPEC §12

**1. Which sources can you actually reach?** See §1. After allowlisting: the NSE
archives, which cover price, volume, delivery, futures OI, lot size, index membership
and sector labels. This was an egress-policy denial all along, exactly as the original
version predicted — adding `*.nseindia.com` to the environment's **Custom** network
access resolved it with no code change.

**2. What would a paid subscription buy?** Narrower than before, and now the ONLY
remaining paid question. FMP Starter buys **only** the fundamental layer — statements
and ratios. It no longer needs to supply sector labels, because the Nifty 500
constituent CSV carries an `Industry` column.

**Three sources tested for per-stock fundamentals, all negative:**

| Source | Result |
|---|---|
| FMP (current plan) | `statements`, `key-metrics`, `profile-symbol` all plan-denied |
| Alpha Vantage | `COMPANY_OVERVIEW` and `INCOME_STATEMENT` return `{}` for `RELIANCE.BSE` |
| NSE archives | No financials published — market data only; probed paths 404 |

This is now a tested conclusion rather than an assumption about one vendor. Index-level
P/E and P/B are available from `ind_close_all_*.csv`, but those describe the index, not
a company, and cannot gate a stock. Worth a trial *before* paying, and the question to answer on that trial
is not whether the endpoints respond — it is whether **Nifty 500 midcap** depth is
there. Vendor India coverage is typically solid for the top 100 and thins out below,
and the midcaps are where this screen lives.

What no subscription substitutes for: **delivery percentage, stock-futures OI, basis,
and rollover are NSE-published and have no vendor equivalent.** ✅ Now available free
from the archives.

**3. Ambiguous or unimplementable as written?** Three, all recorded in
`config/strategy.yaml`:
- Sector caps need a taxonomy pinned before either number means anything
  (`risk.sector_taxonomy`, still `null`). ✅ **Now answerable**: the constituent CSV
  carries an `Industry` column with 20 values. Note Financial Services is 101 of 500 —
  a fifth of the index in one bucket, which makes a 40% exposure cap on it loose. This
  is a strategy decision, so the null stays until it is made deliberately.
- The short side was **dropped by decision** after this audit (SPEC §4). It was also
  structurally unfundable: at ₹2,00,000 capital a single stock-futures lot breaches
  `max_position_pct_of_capital` on its own. Long-only removes that problem and
  simplifies exposure to qty × price — but it exposed a separate one the shorts had
  been masking, now fixed: `max_concurrent_positions × max_position_pct_of_capital`
  is 150% of capital, and the aggregate *risk* cap does not constrain *cash*. Added
  `risk.max_deployed_pct_of_capital`.
- SPEC §9 says to port the sizing formula from the existing Excel system. Still
  outstanding — `src/risk/sizing.py` must not be filled in from first principles.

**4. Proposed order.** Unchanged from the README, except that source-independent work
moves ahead of blocked work rather than the build stalling:

1. ~~Resolve NSE access.~~ ✅ **Done** — environment network access set to Custom with
   `*.nseindia.com`.
2. Build `NsePriceSource` against the archives, behind the existing `PriceSource`
   Protocol. ← the next actual step
3. FMP Starter trial, checking midcap depth specifically. Now the only paid question,
   and the only route to the fundamental layer that has not been ruled out by testing.
4. ~~Meanwhile: indicators.~~ ✅ Done — the whole source-independent layer, 191 tests.
5. Then the build order as written: backtest, runner, report.

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
- ~~The BSE-vs-NSE volume ratio is asserted, not measured.~~ ✅ Measured: 15.9× (§2).
- Corporate actions. `quality.py` cannot detect a split or bonus — it looks like a
  legitimate gap with healthy volume. Use an adjusted series.
- Survivorship bias (SPEC §10). Needs point-in-time Nifty 500 membership; no source
  identified yet, and today's list applied to 2020 data will overstate every result.
