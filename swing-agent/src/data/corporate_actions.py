"""Detect and back-adjust splits and bonus issues.

WHY. NSE bhavcopy prices are UNADJUSTED. RELIANCE closes 2655.70 on 2024-10-25
and 1334.35 on 2024-10-28 - a 1:1 bonus, not a 50% crash. Scanning the Nifty 500
found 117 such events across 105 symbols, 21% of the universe.

Left alone this corrupts a 200-day SMA for roughly 200 sessions after the event,
distorts RSI and ATR around it, and shows a position held across one as a
phantom 50-80% loss.

NSE publishes no corporate-actions file at any archive path probed, so the split
factor has to be recovered from the price series itself.

HOW SPLITS ARE TOLD FROM CRASHES. A split multiplies the price by a simple
fraction - 1/2 for a 1:1 bonus, 1/5 for a 5:1 split, 1/10 for a 10:1. The stock
also moves on the ex-date, so the observed ratio is near the fraction rather than
exactly it. A genuine 50% collapse lands on an arbitrary number like 0.487 with
no reason to sit near 1/2.

WHAT IS DELIBERATELY NOT ADJUSTED. A demerger is not a split. Value leaves for a
new listed entity, the ratio is whatever the market decides the remaining stub is
worth, and no single factor reconstructs a continuous series. Those show up here
as events that match no clean fraction - VEDL at 0.351 and IRB at 0.541 in this
universe. They are REPORTED AND THE SYMBOL IS REFUSED rather than adjusted by
the nearest guess, because an almost-right factor produces a series that looks
continuous and is wrong, which is worse than one that is obviously broken.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import pandas as pd

# Ratios a split or bonus actually produces.
#
# A bonus of a:b (a new shares for every b held) leaves b/(a+b) of the price.
# A split by integer n leaves 1/n. Both use SMALL numbers - companies issue 1:1
# and 1:2 bonuses, not 7:13 ones.
#
# The denominator bound matters more than it looks. An earlier version allowed
# any p/q up to q=20, which put a candidate every 1-2% across the whole range,
# so with any usable tolerance every observed ratio matched something and
# nothing was ever refused. A permissive matcher does not detect splits, it
# launders demergers into them.
def _clean_ratios() -> list[float]:
    out = set()
    # Bonus a:b, small numbers only. Companies issue 1:1, 1:2, 3:2 and 4:1.
    # Nobody issues a 9:7 bonus - allowing a and b up to 10 generated exactly
    # that (7/16 = 0.4375) and swallowed an arbitrary 0.44 ratio, which is the
    # permissiveness failure this set exists to avoid.
    for a in range(1, 6):
        for b in range(1, 6):
            out.add(b / (a + b))
    for n in (2, 3, 4, 5, 6, 8, 10, 20, 50, 100):   # split by n
        out.add(1.0 / n)
    return sorted(r for r in out if 0.005 <= r <= 0.95)


CLEAN_RATIOS = _clean_ratios()


@dataclass
class Adjustment:
    date: pd.Timestamp
    observed_ratio: float
    factor: float | None          # None when nothing clean matched
    kind: str                     # 'split' | 'unmatched' | 'data_gap'
    gap_days: int = 1

    @property
    def adjustable(self) -> bool:
        return self.kind == "split" and self.factor is not None

    def __str__(self) -> str:
        if self.adjustable:
            return (f"{self.date.date()} split x{self.factor:.4f} "
                    f"(observed {self.observed_ratio:.4f})")
        if self.kind == "data_gap":
            return (f"{self.date.date()} DATA GAP of {self.gap_days} days across a "
                    f"{self.observed_ratio:.3f}x move - not a corporate action")
        return (f"{self.date.date()} UNMATCHED ratio {self.observed_ratio:.4f} - "
                f"not a clean split; likely a demerger")


def detect(close: pd.Series, cfg: dict) -> list[Adjustment]:
    """Find suspected corporate actions in a close series."""
    ca = cfg["data_quality"]["corporate_actions"]
    lower, upper = ca["ratio_lower"], ca["ratio_upper"]
    tolerance = ca["clean_ratio_tolerance_pct"] / 100.0

    max_gap = ca["max_gap_days"]
    ratios = (close / close.shift(1)).dropna()
    gaps = close.index.to_series().diff().dt.days
    suspects = ratios[(ratios <= lower) | (ratios >= upper)]

    events: list[Adjustment] = []
    for day, observed in suspects.items():
        observed = float(observed)
        gap = int(gaps.get(day, 1) or 1)

        # A price change measured across a hole in the data is not a corporate
        # action, it is a hole in the data. CGPOWER has no bars between
        # 2021-09-15 and 2022-01-04 and TTML skips five months, because the
        # EQ-series filter drops a stock while it sits in the BE/trade-for-trade
        # segment under surveillance. Reading the prices either side of that as
        # a one-session move produced phantom 2-3x "splits".
        if gap > max_gap:
            events.append(
                Adjustment(day, observed, None, "data_gap", gap_days=gap)
            )
            continue

        factor = _nearest_clean(observed, tolerance)
        events.append(
            Adjustment(
                date=day,
                observed_ratio=observed,
                factor=factor,
                kind="split" if factor is not None else "unmatched",
                gap_days=gap,
            )
        )
    return events


def _nearest_clean(observed: float, tolerance: float) -> float | None:
    """The clean fraction this ratio is within tolerance of, or None.

    Only downward ratios are matched. An upward jump of the same size is a
    reverse split or a data error, and both are rare enough that guessing at
    them is not worth the risk of mangling a real series.
    """
    if observed >= 1.0:
        return None
    best, best_err = None, tolerance
    for value in CLEAN_RATIOS:
        err = abs(observed - value) / value
        if err < best_err:
            best, best_err = value, err
    return best


def adjust(df: pd.DataFrame, events: list[Adjustment]) -> pd.DataFrame:
    """Back-adjust prices for every adjustable event. Does not modify `df`.

    Standard back-adjustment: prices BEFORE the ex-date are multiplied by the
    factor so the series is continuous across it, and volume before the date is
    divided by the same factor so rupee turnover stays comparable. Prices after
    the event are the ones actually traded and are left alone.

    Applied newest-first so that a symbol with two splits compounds correctly:
    bars before the earlier one must carry both factors.
    """
    out = df.copy()
    for event in sorted(events, key=lambda e: e.date, reverse=True):
        if not event.adjustable:
            continue
        mask = out.index < event.date
        if not mask.any():
            continue
        for col in ("open", "high", "low", "close"):
            if col in out.columns:
                out[col] = out[col].astype(float)
                out.loc[mask, col] = out.loc[mask, col] * event.factor
        if "volume" in out.columns:
            # Cast first: bhavcopy volume arrives as int64 and scaling by a
            # fractional factor raises rather than silently truncating.
            out["volume"] = out["volume"].astype(float)
            out.loc[mask, "volume"] = out.loc[mask, "volume"] / event.factor
    return out


def summarise(events: list[Adjustment]) -> str:
    if not events:
        return "no corporate actions detected"
    splits = [e for e in events if e.adjustable]
    gaps = [e for e in events if e.kind == "data_gap"]
    unmatched = [e for e in events if e.kind == "unmatched"]
    parts = []
    if splits:
        parts.append(f"{len(splits)} split(s) adjusted")
    if gaps:
        parts.append(f"{len(gaps)} data gap(s) (symbol refused)")
    if unmatched:
        parts.append(f"{len(unmatched)} unmatched ratio(s) (symbol refused)")
    return "; ".join(parts) or "no corporate actions detected"
