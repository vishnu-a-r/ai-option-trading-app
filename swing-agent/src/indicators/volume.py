"""Volume, participation, and volume-weighted price.

Every function here is only as good as the exchange the volume came from. See
DATA_AUDIT.md section 2: on a feed carrying a minority share of a dual-listed
name's turnover, these read noise. That is a data problem, not a code problem,
but it is the reason none of this should be trusted until the NSE source lands.
"""
from __future__ import annotations

import pandas as pd


def anchored_vwap(df: pd.DataFrame, anchor_idx: int) -> pd.Series:
    """VWAP accumulated forward from an anchor bar.

    Anchor at the last significant swing low. Session VWAP is an intraday tool
    and is meaningless for a multi-day swing hold - do not substitute it.

    Bars before the anchor are NaN rather than zero: the measure does not exist
    yet there, and a zero would read as "price is infinitely above VWAP".
    Typical price (H+L+C)/3 is the weighting price, not close.
    """
    if not 0 <= anchor_idx < len(df):
        raise ValueError(f"anchor_idx {anchor_idx} outside frame of length {len(df)}")

    tail = df.iloc[anchor_idx:]
    typical = (tail["high"] + tail["low"] + tail["close"]) / 3.0
    cum_vol = tail["volume"].cumsum()
    cum_pv = (typical * tail["volume"]).cumsum()

    out = pd.Series(index=df.index, dtype=float)
    out.iloc[anchor_idx:] = (cum_pv / cum_vol.where(cum_vol != 0)).to_numpy()
    return out


def volume_dryup(df: pd.DataFrame, ratio: float, avg_period: int = 20) -> bool:
    """Pullback volume contracting vs average - healthy pullback signature.

    Compares the latest bar's volume to the average of the `avg_period` bars
    BEFORE it. Including the current bar in its own benchmark drags the average
    toward the value being tested and softens the signal.
    """
    _check(ratio, avg_period)
    if len(df) < avg_period + 1:
        return False
    baseline = df["volume"].iloc[-(avg_period + 1) : -1].mean()
    if baseline <= 0:
        return False
    return bool(df["volume"].iloc[-1] < baseline * ratio)


def volume_expansion(df: pd.DataFrame, ratio: float, avg_period: int = 20) -> bool:
    """Expansion on the reversal bar - the confirmation half of the pair."""
    _check(ratio, avg_period)
    if len(df) < avg_period + 1:
        return False
    baseline = df["volume"].iloc[-(avg_period + 1) : -1].mean()
    if baseline <= 0:
        return False
    return bool(df["volume"].iloc[-1] > baseline * ratio)


def delivery_trend(delivery_pct: pd.Series, days: int = 30) -> float:
    """Recent delivery percentage vs its own average. Accumulation proxy.

    Returns the ratio of the latest reading to the trailing `days` average, so
    1.0 is "in line" and above 1.0 is rising delivery.

    NO SOURCE YET. Delivery percentage is NSE-published with no vendor
    equivalent (DATA_AUDIT.md section 1). This function is correct and untested
    against real data because there is none to test against.
    """
    if days < 1:
        raise ValueError(f"days must be >= 1, got {days}")
    clean = delivery_pct.dropna()
    if len(clean) < days + 1:
        return float("nan")
    baseline = clean.iloc[-(days + 1) : -1].mean()
    if baseline <= 0:
        return float("nan")
    return float(clean.iloc[-1] / baseline)


def _check(ratio: float, avg_period: int) -> None:
    if ratio <= 0:
        raise ValueError(f"ratio must be > 0, got {ratio}")
    if avg_period < 1:
        raise ValueError(f"avg_period must be >= 1, got {avg_period}")
