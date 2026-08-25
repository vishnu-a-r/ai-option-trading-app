"""Momentum oscillators."""
from __future__ import annotations

import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's smoothing, not a simple average - they diverge materially.

    Wilder's is an EMA with alpha = 1/period. A simple rolling mean of gains and
    losses gives a visibly different oscillator, and the long screen gates on
    RSI being inside [30, 60] - a band narrow enough that the difference decides
    whether a stock is screened at all. There is a test asserting the two
    diverge; if someone swaps this for .rolling().mean() it fails.

    Seeded with a simple mean of the first `period` changes, per Wilder.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    if len(close) < period + 1:
        return pd.Series(index=close.index, dtype=float)

    avg_gain = _wilder(gain, period)
    avg_loss = _wilder(loss, period)

    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    # avg_loss == 0 means an unbroken run of up bars: RSI is 100, not NaN.
    out[avg_loss == 0] = 100.0
    out[(avg_gain == 0) & (avg_loss == 0)] = 50.0
    return out


def stochastic(df: pd.DataFrame, k: int, d: int, smooth: int) -> pd.DataFrame:
    """Returns %K and %D columns.

    %K is the raw stochastic smoothed by `smooth`; %D is the moving average of
    %K over `d`. A flat window (high == low over the whole lookback) has no
    defined position within its range - that is NaN, not 50.
    """
    for name, value in [("k", k), ("d", d), ("smooth", smooth)]:
        if value < 1:
            raise ValueError(f"{name} must be >= 1, got {value}")

    low_k = df["low"].rolling(window=k, min_periods=k).min()
    high_k = df["high"].rolling(window=k, min_periods=k).max()
    span = high_k - low_k
    raw = 100.0 * (df["close"] - low_k) / span.where(span != 0)

    percent_k = raw.rolling(window=smooth, min_periods=smooth).mean()
    percent_d = percent_k.rolling(window=d, min_periods=d).mean()
    return pd.DataFrame({"k": percent_k, "d": percent_d}, index=df.index)


def macd(close: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:
    """Returns macd, signal, histogram.

    For the pullback setup we want histogram *contracting toward* a bullish
    cross, not the cross itself - by the cross the entry is often gone. See
    histogram_contracting().
    """
    if fast >= slow:
        raise ValueError(f"fast ({fast}) must be < slow ({slow})")

    fast_ema = close.ewm(span=fast, adjust=False).mean()
    slow_ema = close.ewm(span=slow, adjust=False).mean()
    line = fast_ema - slow_ema
    sig = line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame(
        {"macd": line, "signal": sig, "histogram": line - sig}, index=close.index
    )


def histogram_contracting(hist: pd.Series, bars: int = 3) -> bool:
    """A negative histogram shrinking toward zero over the last `bars`.

    This is the pullback confirmation the SPEC asks for, and it is deliberately
    not "histogram crossed above zero": by the cross the entry is usually gone.
    Requires the histogram to still be below zero - a positive histogram that is
    shrinking is momentum fading, the opposite signal.
    """
    if bars < 2:
        raise ValueError(f"bars must be >= 2, got {bars}")
    window = hist.dropna().tail(bars)
    if len(window) < bars:
        return False
    if window.iloc[-1] >= 0:
        return False
    return bool((window.diff().dropna() > 0).all())


def _wilder(series: pd.Series, period: int) -> pd.Series:
    """EMA with alpha = 1/period, seeded with a simple mean of the first window."""
    out = pd.Series(index=series.index, dtype=float)
    seed = series.iloc[1 : period + 1].mean()
    out.iloc[period] = seed
    prev = seed
    for i in range(period + 1, len(series)):
        prev = (prev * (period - 1) + series.iloc[i]) / period
        out.iloc[i] = prev
    return out
