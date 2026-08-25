"""Long setup: momentum pullback in an established uptrend."""
from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class SetupResult:
    symbol: str
    passed: bool
    gate_failures: list[str] = field(default_factory=list)  # why it was rejected
    confirmations: dict[str, float] = field(default_factory=dict)  # scored, 0..1
    entry: float | None = None
    stop: float | None = None
    targets: list[float] = field(default_factory=list)
    reason: str = ""


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
