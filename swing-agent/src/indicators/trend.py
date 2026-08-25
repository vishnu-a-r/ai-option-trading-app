"""Trend and structure. Pure functions on a single symbol's OHLCV frame."""
from __future__ import annotations

import pandas as pd

from .pivots import confirmed_as_of, swing_points


def sma(close: pd.Series, period: int) -> pd.Series:
    _check_period(period)
    return close.rolling(window=period, min_periods=period).mean()


def ema(close: pd.Series, period: int) -> pd.Series:
    _check_period(period)
    return close.ewm(span=period, adjust=False, min_periods=period).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    """max(high-low, |high-prev_close|, |low-prev_close|).

    NOTE ON GAPS. `prev_close` is the previous row's close, which after
    quality.clean_ohlcv() may be several calendar days back - the dropped bars
    did not trade. That is correct and deliberate: the price genuinely moved
    from that close to this bar's range with no trading in between, and the gap
    is real range. Do NOT "fix" this by reindexing onto a calendar and forward
    filling; that reintroduces exactly the zero-range bars quality.py removed.
    """
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range, WILDER smoothing.

    Wilder's is an EMA with alpha = 1/period, NOT a simple rolling mean and NOT
    an EMA with the usual span=period (which is alpha = 2/(period+1), roughly
    twice as fast). The three disagree materially and ATR is what sizes every
    position through risk.atr_stop_buffer, so the difference is rupees. There is
    a test asserting Wilder and simple diverge; if someone swaps this for
    .rolling().mean() it fails.

    Seeded with a simple mean of the first `period` true ranges, which is
    Wilder's own initialisation.
    """
    _check_period(period)
    tr = true_range(df)
    if len(tr) < period + 1:
        return pd.Series(index=df.index, dtype=float)

    # TR at position 0 is NaN (no previous close), so seed from positions 1..period.
    out = pd.Series(index=df.index, dtype=float)
    seed = tr.iloc[1 : period + 1].mean()
    out.iloc[period] = seed
    prev = seed
    for i in range(period + 1, len(tr)):
        prev = (prev * (period - 1) + tr.iloc[i]) / period
        out.iloc[i] = prev
    return out


def is_uptrend_structure(
    df: pd.DataFrame,
    pivot_lookback: int,
    min_pairs: int,
    as_of_bar: int | None = None,
) -> bool:
    """Higher highs AND higher lows, detected from swing pivots.

    This must be programmatic - the whole point is to not eyeball it.

    `as_of_bar` is not optional decoration. Pivots are only knowable
    `pivot_lookback` bars after they print (see swing_points), so a structure
    check that reads the whole frame is reading the future. Callers standing at
    bar N pass as_of_bar=N and get only what the market had actually confirmed
    by then. Default is the last bar, which is correct for live screening and
    wrong for a backtest loop - the backtest must pass its own cursor.
    """
    if min_pairs < 1:
        raise ValueError(f"min_pairs must be >= 1, got {min_pairs}")

    cursor = len(df) - 1 if as_of_bar is None else as_of_bar
    pivots = confirmed_as_of(swing_points(df, pivot_lookback), cursor)
    if pivots.empty:
        return False

    highs = pivots[pivots["kind"] == "high"]["price"].tail(min_pairs)
    lows = pivots[pivots["kind"] == "low"]["price"].tail(min_pairs)
    if len(highs) < min_pairs or len(lows) < min_pairs:
        return False

    return _ascending(highs) and _ascending(lows)


def relative_strength(close: pd.Series, benchmark: pd.Series, period: int) -> float:
    """Symbol return minus benchmark return over `period` bars."""
    _check_period(period)
    if len(close) <= period or len(benchmark) <= period:
        return float("nan")
    sym = close.iloc[-1] / close.iloc[-1 - period] - 1.0
    bench = benchmark.iloc[-1] / benchmark.iloc[-1 - period] - 1.0
    return float(sym - bench)


def _ascending(values: pd.Series) -> bool:
    return bool((values.diff().dropna() > 0).all()) if len(values) > 1 else True


def _check_period(period: int) -> None:
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
