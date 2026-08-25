"""Momentum oscillators."""
from __future__ import annotations
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's smoothing, not a simple average - they diverge materially."""


def stochastic(df: pd.DataFrame, k: int, d: int, smooth: int) -> pd.DataFrame:
    """Returns %K and %D columns."""


def macd(close: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:
    """Returns macd, signal, histogram.

    For the pullback setup we want histogram *contracting toward* a bullish
    cross, not the cross itself - by the cross the entry is often gone.
    """
