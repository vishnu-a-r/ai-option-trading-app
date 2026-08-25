"""Volume, participation, and volume-weighted price."""
from __future__ import annotations
import pandas as pd


def anchored_vwap(df: pd.DataFrame, anchor_idx: int) -> pd.Series:
    """VWAP accumulated forward from an anchor bar.

    Anchor at the last significant swing low. Session VWAP is an intraday tool
    and is meaningless for a multi-day swing hold - do not substitute it.
    """


def volume_dryup(df: pd.DataFrame, ratio: float, avg_period: int = 20) -> bool:
    """Pullback volume contracting vs average - healthy pullback signature."""


def volume_expansion(df: pd.DataFrame, ratio: float, avg_period: int = 20) -> bool:
    """Expansion on the reversal bar - the confirmation half of the pair."""


def delivery_trend(delivery_pct: pd.Series, days: int = 30) -> float:
    """Recent delivery percentage vs its own average. Accumulation proxy."""
