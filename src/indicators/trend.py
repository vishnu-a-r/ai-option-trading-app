"""Trend and structure. Pure functions on a single symbol's OHLCV frame."""
from __future__ import annotations
import pandas as pd


def sma(close: pd.Series, period: int) -> pd.Series: ...


def ema(close: pd.Series, period: int) -> pd.Series: ...


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series: ...


def is_uptrend_structure(df: pd.DataFrame, pivot_lookback: int, min_pairs: int) -> bool:
    """Higher highs AND higher lows, detected from swing pivots.

    This must be programmatic - the whole point is to not eyeball it. Use
    pivots.swing_points(), then check the last `min_pairs` highs are ascending
    and the last `min_pairs` lows are ascending.
    """


def is_downtrend_structure(df: pd.DataFrame, pivot_lookback: int, min_pairs: int) -> bool:
    """Lower highs AND lower lows. Mirror of the above."""


def relative_strength(close: pd.Series, benchmark: pd.Series, period: int) -> float:
    """Symbol return minus benchmark return over `period` bars."""
