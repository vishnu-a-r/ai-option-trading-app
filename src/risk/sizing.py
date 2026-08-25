"""Position sizing and portfolio-level risk caps.

DO NOT invent a sizing formula. Vishnu has a fixed-fractional formula already
in use in an Excel swing system - ask for it and port it exactly. A different
formula makes every backtest number incomparable to his live record.
"""
from __future__ import annotations


def stop_level(df, side: str, cfg: dict) -> float:
    """Long: below the pullback swing low, minus an ATR buffer.
    Short: above the rejection high, plus an ATR buffer.
    """


def position_size(entry: float, stop: float, capital: float, cfg: dict) -> int:
    """Fixed fractional: risk_amount = capital * risk_per_trade_pct;
    qty = risk_amount / abs(entry - stop). Round down to lot size for F&O.

    TODO confirm against the Excel formula before any live use.
    """


def portfolio_gates(open_positions: list, candidate, cfg: dict) -> list[str]:
    """Return blocking reasons: max concurrent positions, sector exposure cap,
    aggregate open risk cap. A candidate that passes the screen can still be
    correctly refused here."""
