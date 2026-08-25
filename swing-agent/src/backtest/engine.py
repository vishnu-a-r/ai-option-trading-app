"""Backtest. Nothing goes live until this reports honest numbers.

Minimum: 5 years, must include 2020 and the 2022 drawdown.

Report: win rate, average R multiple, max drawdown, longest losing streak, and
results split by market regime (trending vs range-bound).

SURVIVORSHIP BIAS: screening the *current* Nifty 500 over history is a
look-ahead error - it silently excludes every stock that fell out of the index.
Use point-in-time constituents if the data allows. If it does not, say so
explicitly in the report rather than quietly overstating returns.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BacktestReport:
    trades: int
    win_rate: float
    avg_r: float
    max_drawdown: float
    longest_losing_streak: int
    by_regime: dict[str, dict]
    survivorship_corrected: bool
    notes: list[str]


def run(start, end, cfg, sources) -> BacktestReport: ...


def classify_regime(index_df) -> "pd.Series":
    """Trending vs range-bound, on the index. A pullback system's edge is
    regime-dependent and a single blended number hides that."""
