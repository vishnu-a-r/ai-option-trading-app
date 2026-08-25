"""Long setup: momentum pullback in an established uptrend.

The only screen in this system. Shorts were dropped by decision - see SPEC.md
section 4. Do not add an inverted copy of this file.
"""
from __future__ import annotations
import pandas as pd

from .result import SetupResult


def evaluate(df: pd.DataFrame, symbol: str, cfg: dict, ctx: dict) -> SetupResult:
    """Apply gates, then score confirmations.

    Gates (all must hold, per config):
      - close above 50 SMA
      - 50 SMA above 200 SMA
      - higher-high / higher-low structure
      - RSI(14) in [30, 60]

    Confirmations (scored, never gating): stochastic turning up from oversold,
    MACD histogram contracting, volume dry-up then expansion, price above
    anchored VWAP from last swing low, weekly CPR position, relative strength.

    Always populate gate_failures even on a pass-adjacent reject - the daily
    report shows near-misses with the specific failing condition.
    """
