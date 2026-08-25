"""Swing pivots and CPR."""
from __future__ import annotations
import pandas as pd


def swing_points(df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Fractal pivots: a high with `lookback` lower highs each side, and vice versa.

    Returns a frame of (index, price, kind) where kind is 'high' or 'low'.
    Everything structural depends on this - test it hard.
    """


def cpr(df: pd.DataFrame, timeframe: str = "weekly") -> pd.DataFrame:
    """Central Pivot Range: pivot, BC, TC.

    Timeframe must be weekly or monthly for swing use. Narrow CPR implies a
    trending expectation; wide implies range. Daily CPR is an intraday
    construct and is not appropriate here.
    """


def support_resistance_levels(df: pd.DataFrame, lookback: int) -> list[float]:
    """Prior pivot clusters - used for the short setup's rejection test."""
