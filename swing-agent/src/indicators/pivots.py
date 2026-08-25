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


RESAMPLE_RULE = {"weekly": "W", "monthly": "ME"}


def cpr(df: pd.DataFrame, timeframe: str = "weekly") -> pd.DataFrame:
    """Central Pivot Range: pivot, BC, TC.

    Timeframe must be weekly or monthly for swing use. Narrow CPR implies a
    trending expectation; wide implies range. Daily CPR is an intraday
    construct and is not appropriate here, so "daily" is rejected rather than
    quietly computed.

    Each period's CPR is derived from the PRIOR period's H/L/C, which is what
    makes it usable - this week's levels are known on Monday morning. The
    returned frame is indexed by the period the levels apply TO, not the period
    they were computed from.
    """
    if timeframe not in RESAMPLE_RULE:
        raise ValueError(
            f"timeframe must be one of {sorted(RESAMPLE_RULE)}, got {timeframe!r}. "
            f"Daily CPR is an intraday construct and is not valid for swing use."
        )

    rule = RESAMPLE_RULE[timeframe]
    agg = df.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(agg) < 2:
        return pd.DataFrame(columns=["pivot", "bc", "tc", "width"])

    prior = agg.shift(1).dropna()
    pivot = (prior["high"] + prior["low"] + prior["close"]) / 3.0
    bc = (prior["high"] + prior["low"]) / 2.0
    tc = 2.0 * pivot - bc
    # TC and BC are unordered by construction; the band is between them.
    upper = pd.concat([bc, tc], axis=1).max(axis=1)
    lower = pd.concat([bc, tc], axis=1).min(axis=1)
    return pd.DataFrame(
        {"pivot": pivot, "bc": lower, "tc": upper, "width": (upper - lower) / pivot},
        index=prior.index,
    )


def support_resistance_levels(
    df: pd.DataFrame, lookback: int, tolerance_pct: float = 1.0
) -> list[float]:
    """Prior pivot clusters, as sorted price levels.

    For the long screen these are overhead supply: the levels a pullback entry
    has to clear, and the natural places to set targets.

    Pivots within `tolerance_pct` of each other are one level, averaged - three
    rejections off the same price are one wall, not three, and counting them
    separately would make a busy chart look like it has more structure than it
    does. Only confirmed pivots are used, so this inherits the lookahead
    guarantee from swing_points().
    """
    if tolerance_pct <= 0:
        raise ValueError(f"tolerance_pct must be > 0, got {tolerance_pct}")

    pivots = swing_points(df, lookback)
    if pivots.empty:
        return []

    levels: list[float] = []
    cluster: list[float] = []
    for price in sorted(pivots["price"].tolist()):
        if cluster and (price - cluster[0]) / cluster[0] * 100.0 > tolerance_pct:
            levels.append(sum(cluster) / len(cluster))
            cluster = []
        cluster.append(price)
    if cluster:
        levels.append(sum(cluster) / len(cluster))
    return levels
