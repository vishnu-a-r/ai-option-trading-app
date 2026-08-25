"""Fundamental scoring. Gate for longs, inverted flag for shorts."""
from __future__ import annotations
import pandas as pd


def score(symbol: str, ratios: pd.DataFrame, statements: pd.DataFrame, cfg: dict) -> dict:
    """Return {'score': 0..100, 'components': {...}}.

    Components: growth consistency (3Y + TTM), ROE/ROCE, D/E and interest
    coverage, OCF-to-PAT (earnings quality), promoter holding trend and pledge,
    PE vs own 5Y median and vs sector median.

    Never a single opaque number - the report shows the breakdown so a low rank
    can be interrogated.
    """


def sector_thresholds(sector: str, cfg: dict) -> dict:
    """Banking and NBFC ratios are not comparable to manufacturing.

    D/E is meaningless for a bank; ROCE is not the right capital metric there.
    Resolve the applicable threshold set here rather than branching inside
    score().
    """


def deterioration_flags(symbol: str, statements: pd.DataFrame, cfg: dict) -> list[str]:
    """Short-side signals: falling margin trend, rising debt, negative OCF,
    increasing promoter pledge, auditor or governance flags."""
