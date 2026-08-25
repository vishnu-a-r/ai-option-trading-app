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
    """Return blocking reasons: max concurrent positions, sector risk cap,
    sector notional cap, aggregate open risk cap. A candidate that passes the
    screen can still be correctly refused here.

    The sector cap is two numbers, not one - see the risk block in
    config/strategy.yaml. max_sector_risk_pct is the binding constraint and is
    summed over rupee risk at stop, not position value; max_sector_exposure_pct
    is a notional bound checked alongside it. Both need candidate.sector, which
    must come from the taxonomy pinned at cfg['risk']['sector_taxonomy'] rather
    than whatever sector field a given data provider returns.

    Exposure is notional on both sides. For a futures short that is lot_size *
    price, not the margin blocked.

    Return every reason that fires, not the first - the report shows why a
    ranked candidate was refused, and "capped" without the specific gate is not
    an answer.
    """
