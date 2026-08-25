"""Short setup: F&O-only breakdown with deteriorating fundamentals.

This is NOT an inverted long screen. Inverting it surfaces strong companies in
temporary pullbacks, which is the worst possible short. The fundamental
direction must be independently negative - see screens/fundamental.py.
"""
from __future__ import annotations
import pandas as pd
from .long_pullback import SetupResult


def evaluate(df: pd.DataFrame, symbol: str, cfg: dict, ctx: dict) -> SetupResult:
    """Gates: F&O eligible, close below 50 SMA, 50 below 200, LH/LL structure,
    RSI(14) in [40, 70], rejection at prior support-turned-resistance or a
    declining 20 SMA, and a negative fundamental flag.

    Every returned signal must carry lot size, margin requirement, and current
    basis in `reason` - a short signal is unusable without them.
    """
