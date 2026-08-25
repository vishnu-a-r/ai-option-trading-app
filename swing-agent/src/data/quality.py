"""OHLCV bar-quality screening.

Runs between the data layer and the indicator layer. Nothing in src/indicators/
should ever see a bar that did not really trade.

WHY THIS EXISTS - a real bar from the audit, not a hypothetical:

    RELIANCE.BSE  2026-06-26  o=h=l=c=1318.25  volume=0

That single carried-forward bar does three things downstream:

  * True Range for the bar is 0, which drags ATR(14) below the real value.
    ATR is what risk.atr_stop_buffer multiplies, so a corrupted ATR moves the
    stop, and the stop is what sizes the position. A quiet 7% error in ATR is
    a quiet 7% error in every rupee figure the system prints.
  * A 20-day average volume that includes zeros is understated, so
    volume_dryup() sees contraction that is not there and
    volume_expansion() misses expansion that is.
  * high == low makes the bar simultaneously a swing high and a swing low
    candidate, which puts noise into the structure detection everything else
    is built on.

Dropping the bar is correct rather than filling it: no trade happened, so
there is no price to interpolate and inventing one is worse than the gap.

WHAT IS NOT HANDLED HERE: corporate actions. A split or bonus shows up as a
legitimate-looking gap with healthy volume and passes every check below. Use
an adjusted price series; this module cannot detect the difference.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

OHLC = ["open", "high", "low", "close"]
REQUIRED = OHLC + ["volume"]


@dataclass
class QualityReport:
    """What was removed from one symbol's series, and whether it is usable.

    `usable` is the answer the caller wants. A series can be cleaned and still
    be unfit: a symbol that needed 30% of its bars dropped is a data problem,
    not a tradeable instrument, and silently screening the survivors is how a
    bad symbol reaches a signal list.
    """

    symbol: str
    bars_in: int
    bars_out: int
    dropped: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def dropped_total(self) -> int:
        return self.bars_in - self.bars_out

    @property
    def stale_pct(self) -> float:
        return 100.0 * self.dropped_total / self.bars_in if self.bars_in else 0.0

    @property
    def usable(self) -> bool:
        return not self.reasons

    def __str__(self) -> str:
        head = f"{self.symbol}: {self.bars_in} -> {self.bars_out} bars ({self.stale_pct:.1f}% dropped)"
        detail = ", ".join(f"{k}={v}" for k, v in sorted(self.dropped.items()) if v)
        if detail:
            head += f" [{detail}]"
        if self.reasons:
            head += " REJECTED: " + "; ".join(self.reasons)
        return head


def bar_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Per-bar boolean flags, one column per defect. Does not modify `df`.

    Separated from clean_ohlcv() so a caller can inspect *which* bars are bad
    without having them disappear - when a screen refuses a symbol, the report
    should be able to show the offending bars.
    """
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV frame is missing columns: {missing}")

    o, h, l, c = (df[x] for x in OHLC)
    v = df["volume"]

    flags = pd.DataFrame(index=df.index)
    flags["nan_field"] = df[REQUIRED].isna().any(axis=1)
    flags["non_positive_price"] = (df[OHLC] <= 0).any(axis=1)
    flags["negative_volume"] = v < 0
    flags["zero_volume"] = v.fillna(0) == 0
    flags["flat_bar"] = h == l
    # A bar that trades outside its own high/low is corrupt regardless of volume.
    flags["inconsistent"] = (
        (h < l)
        | (h < o)
        | (h < c)
        | (l > o)
        | (l > c)
    )
    return flags.fillna(False)


def clean_ohlcv(
    df: pd.DataFrame,
    cfg: dict,
    symbol: str = "?",
) -> tuple[pd.DataFrame, QualityReport]:
    """Drop unusable bars and report whether what remains can be screened.

    `cfg` is the data_quality block of config/strategy.yaml. Thresholds are not
    hardcoded here - config/strategy.yaml owns every number in this project.

    Returns (clean_df, report). The caller checks `report.usable` and excludes
    the symbol if False; it does NOT get a silently patched series back.

    Index handling: duplicate timestamps keep the last occurrence (a corrected
    bar republished for the same date supersedes the original) and the result
    is sorted ascending, because every indicator downstream assumes monotonic
    time and none of them check.
    """
    if not isinstance(cfg, dict):
        raise TypeError("cfg must be the data_quality mapping from strategy.yaml")

    bars_in = len(df)
    out = df[~df.index.duplicated(keep="last")].sort_index()
    dropped = {"duplicate_index": bars_in - len(out)}

    flags = bar_flags(out)

    # Always fatal - these are corrupt rather than merely untraded.
    kill = flags["nan_field"] | flags["non_positive_price"] | flags["negative_volume"] | flags["inconsistent"]
    if cfg.get("drop_zero_volume_bars", True):
        kill = kill | flags["zero_volume"]
    if cfg.get("drop_flat_bars", True):
        kill = kill | flags["flat_bar"]

    for name in flags.columns:
        dropped[name] = int((flags[name] & kill).sum())

    clean = out[~kill]
    report = QualityReport(symbol=symbol, bars_in=bars_in, bars_out=len(clean), dropped=dropped)

    max_stale = cfg.get("max_stale_bar_pct")
    if max_stale is not None and report.stale_pct > max_stale:
        report.reasons.append(
            f"{report.stale_pct:.1f}% of bars unusable (limit {max_stale}%)"
        )

    min_bars = cfg.get("min_bars_required")
    if min_bars is not None and report.bars_out < min_bars:
        report.reasons.append(f"{report.bars_out} clean bars (need {min_bars})")

    return clean, report
