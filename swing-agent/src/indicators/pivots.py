"""Swing pivots and CPR."""
from __future__ import annotations

import pandas as pd

PIVOT_COLUMNS = ["bar", "date", "price", "kind", "confirmed_at_bar", "confirmed_at_date"]


def swing_points(df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Fractal pivots: a high with `lookback` lower highs each side, and vice versa.

    Returns a frame of (bar, date, price, kind, confirmed_at_bar,
    confirmed_at_date) where kind is 'high' or 'low', sorted by bar.
    Everything structural depends on this - test it hard.

    LOOKAHEAD. A fractal pivot is not knowable when it prints. Bar i is only
    confirmed as a swing high once `lookback` further bars have closed lower,
    so its information is available at bar i + lookback and not before. That is
    what `confirmed_at_bar` records, and it is the column a backtest must filter
    on. Filtering on `bar` instead lets the screen see a swing low up to
    `lookback` days before the market did, which flatters every entry price in
    the run. The last `lookback` bars of any frame therefore never contain a
    pivot - that is correct, not an off-by-one.

    TIES. Equal highs are common on low-tick-size names and a strict comparison
    on both sides silently discards a genuine double top. The rule here is
    `>=` looking left and `>` looking right, which resolves a plateau to its
    LAST bar, deterministically and exactly once. The mirror applies to lows.

    Nothing is inferred about alternation: two highs can appear with no low
    between them. Callers that need strict alternation must impose it
    themselves rather than assuming this returns it.
    """
    if lookback < 1:
        raise ValueError(f"lookback must be >= 1, got {lookback}")
    for col in ("high", "low"):
        if col not in df.columns:
            raise ValueError(f"frame is missing '{col}'")

    n = len(df)
    if n < 2 * lookback + 1:
        return pd.DataFrame(columns=PIVOT_COLUMNS)

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)

    rows: list[tuple] = []
    dates = df.index
    for i in range(lookback, n - lookback):
        left = slice(i - lookback, i)
        right = slice(i + 1, i + lookback + 1)
        confirm = i + lookback
        if high[i] >= high[left].max() and high[i] > high[right].max():
            rows.append((i, dates[i], high[i], "high", confirm, dates[confirm]))
        if low[i] <= low[left].min() and low[i] < low[right].min():
            rows.append((i, dates[i], low[i], "low", confirm, dates[confirm]))

    out = pd.DataFrame(rows, columns=PIVOT_COLUMNS)
    return out.sort_values("bar", kind="stable").reset_index(drop=True)


def confirmed_as_of(pivots: pd.DataFrame, bar: int) -> pd.DataFrame:
    """The pivots a screen standing at `bar` is allowed to know about.

    Use this in the backtest rather than slicing on the pivot's own bar index.
    See the LOOKAHEAD note in swing_points().
    """
    if pivots.empty:
        return pivots
    return pivots[pivots["confirmed_at_bar"] <= bar]


def cpr(df: pd.DataFrame, timeframe: str = "weekly") -> pd.DataFrame:
    """Central Pivot Range: pivot, BC, TC.

    Timeframe must be weekly or monthly for swing use. Narrow CPR implies a
    trending expectation; wide implies range. Daily CPR is an intraday
    construct and is not appropriate here.
    """


def support_resistance_levels(df: pd.DataFrame, lookback: int) -> list[float]:
    """Prior pivot clusters - used for the short setup's rejection test."""
