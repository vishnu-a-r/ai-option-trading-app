"""Stops, position sizing, and portfolio-level risk caps.

DO NOT invent a sizing formula. Vishnu has a fixed-fractional formula already
in use in an Excel swing system - ask for it and port it exactly. A different
formula makes every backtest number incomparable to his live record. That is
why position_size() below raises instead of returning a plausible number.

Long-only, cash equity (SPEC.md section 4), so exposure is qty * price.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..config import require
from ..indicators.pivots import confirmed_as_of, swing_points
from ..indicators.trend import atr


@dataclass
class Position:
    """An open position, as the portfolio gates need to see it."""

    symbol: str
    sector: str
    qty: int
    entry: float
    stop: float

    @property
    def exposure(self) -> float:
        """Cash at work. Long-only equity, so notional is just qty * price."""
        return self.qty * self.entry

    @property
    def risk_amount(self) -> float:
        """Rupees between entry and stop. What the risk caps actually sum."""
        return self.qty * abs(self.entry - self.stop)


def stop_level(df: pd.DataFrame, cfg: dict, as_of_bar: int | None = None) -> float | None:
    """Structural stop: below the last confirmed swing low, minus an ATR buffer.

    Returns None when there is no confirmed swing low to anchor to. That is a
    refusal to trade, NOT an invitation to fall back on a percentage.

    THERE IS NO FIXED PERCENTAGE STOP ANYWHERE ON ANY PATH. The config comment
    says so and this is the function where the temptation actually appears: the
    edge case is real (an early bar, a short history, a symbol with no clean
    pivots) and a 2% fallback would look like defensive programming. It is not.
    A fixed 2% sits inside one day's normal range for most Nifty 500 midcaps, so
    the fallback would quietly produce a stop that gets swept on noise, on
    exactly the setups where structure was hardest to read. No stop, no trade.

    The anchor uses confirmed pivots only, so a backtest standing at `as_of_bar`
    cannot anchor to a swing low the market had not yet confirmed.
    """
    period = cfg["risk"]["atr_period"]
    buffer_multiple = cfg["risk"]["atr_stop_buffer"]
    lookback = cfg["long_pullback"]["trend"]["pivot_lookback"]

    cursor = len(df) - 1 if as_of_bar is None else as_of_bar
    pivots = confirmed_as_of(swing_points(df, lookback), cursor)
    lows = pivots[pivots["kind"] == "low"]
    if lows.empty:
        return None

    atr_series = atr(df.iloc[: cursor + 1], period)
    if atr_series.empty or pd.isna(atr_series.iloc[-1]):
        return None

    return float(lows["price"].iloc[-1] - buffer_multiple * atr_series.iloc[-1])


def position_size(entry: float, stop: float, capital: float, cfg: dict) -> int:
    """Fixed fractional. Rupee risk is fixed; QUANTITY is the output.

    SOURCE OF TRUTH. SPEC section 9 asked for the formula to be ported from an
    existing Excel system. That system does not exist - confirmed with Vishnu,
    2026-08-25 - so the specification is the risk block in strategy.yaml, which
    states the order of operations explicitly. Nothing here is invented; it is
    the config comment executed. The earlier concern about matching an Excel
    record is moot when there is no record to match.

    Order, and it does not commute:

      1. risk_amount = capital * risk_per_trade_pct / 100     (fixed, Rs 2,000)
      2. qty         = risk_amount / abs(entry - stop)        (size is derived)
      3. truncate to max_position_pct_of_capital              (cap binds AFTER)
      4. floor to whole shares                                (cash equity)

    Step 3 after step 2 is what the config means by "this cap binds first and
    truncates it": the formula asks for a size, the cap cuts it down. Applying
    the cap first and then deriving risk would invert the whole design - risk
    would become an output of position size, which is the thing the block
    exists to prevent.

    A truncated position carries LESS than the full rupee risk. That is
    intended, not a bug, and the caller should log it - see `binds` in
    size_with_reason().

    Returns 0 when the stop is at or through the entry, or when one full share
    cannot be afforded within the cap. Zero means no trade.
    """
    qty, _ = size_with_reason(entry, stop, capital, cfg)
    return qty


def size_with_reason(
    entry: float, stop: float, capital: float, cfg: dict
) -> tuple[int, str | None]:
    """position_size(), plus why the number came out the way it did.

    The report has to be able to say "the concentration cap truncated this",
    because on a tight-stop setup the effective risk is below 1% and a reader
    comparing two lines of the shortlist deserves to know which one that
    happened to.
    """
    risk = cfg["risk"]
    if entry <= 0:
        raise ValueError(f"entry must be positive, got {entry}")
    if stop >= entry:
        return 0, "stop at or above entry: not a long setup"

    risk_amount = capital * risk["risk_per_trade_pct"] / 100.0
    per_share = entry - stop
    wanted = risk_amount / per_share

    cap_value = capital * risk["max_position_pct_of_capital"] / 100.0
    cap_qty = cap_value / entry

    binds = cap_qty < wanted
    qty = int(min(wanted, cap_qty))     # floor: cash equity trades whole shares

    if qty == 0:
        return 0, f"one share at {entry:.2f} exceeds the {risk['max_position_pct_of_capital']}% cap"
    if binds:
        actual = 100.0 * qty * per_share / capital
        return qty, (
            f"max_position_pct_of_capital truncated {wanted:.0f} -> {qty}; "
            f"effective risk {actual:.2f}% not {risk['risk_per_trade_pct']}%"
        )
    return qty, None


def portfolio_gates(open_positions: list[Position], candidate, cfg: dict) -> list[str]:
    """Return every blocking reason. A candidate that passes the screen can
    still be correctly refused here.

    Five caps: concurrent positions, sector risk, sector exposure, aggregate
    open risk, and deployed capital.

    Returns ALL reasons that fire, not the first. The daily report has to name
    the specific gate, and "capped" without which cap is not an answer.

    Risk and cash are separate constraints and both are checked. Six tight-stop
    positions can sit inside the 6% aggregate risk cap while asking for 150% of
    the account - see the comment on max_deployed_pct_of_capital.

    The sector caps call require(cfg, "risk.sector_taxonomy"), which raises
    until a taxonomy is pinned. That is correct: without a label the sector
    caps are unenforceable, and silently skipping them would let a portfolio
    concentrate in one sector while the report claimed a cap was in force.
    """
    risk = cfg["risk"]
    capital = risk["capital_inr"]
    reasons: list[str] = []

    if len(open_positions) >= risk["max_concurrent_positions"]:
        reasons.append(
            f"max_concurrent_positions: {len(open_positions)} open, "
            f"limit {risk['max_concurrent_positions']}"
        )

    open_risk = sum(p.risk_amount for p in open_positions)
    new_risk = candidate.risk_amount
    aggregate_limit = capital * risk["max_aggregate_open_risk_pct"] / 100.0
    if open_risk + new_risk > aggregate_limit:
        reasons.append(
            f"max_aggregate_open_risk_pct: {_pct(open_risk + new_risk, capital)} "
            f"would be at risk, limit {risk['max_aggregate_open_risk_pct']}%"
        )

    open_exposure = sum(p.exposure for p in open_positions)
    new_exposure = candidate.exposure
    deployed_limit = capital * risk["max_deployed_pct_of_capital"] / 100.0
    if open_exposure + new_exposure > deployed_limit:
        reasons.append(
            f"max_deployed_pct_of_capital: {_pct(open_exposure + new_exposure, capital)} "
            f"deployed, limit {risk['max_deployed_pct_of_capital']}%"
        )

    # Raises UnresolvedConfig while the taxonomy is null - deliberately.
    require(cfg, "risk.sector_taxonomy")

    same_sector = [p for p in open_positions if p.sector == candidate.sector]
    sector_risk = sum(p.risk_amount for p in same_sector) + new_risk
    sector_risk_limit = capital * risk["max_sector_risk_pct"] / 100.0
    if sector_risk > sector_risk_limit:
        reasons.append(
            f"max_sector_risk_pct: {candidate.sector} would carry "
            f"{_pct(sector_risk, capital)}, limit {risk['max_sector_risk_pct']}%"
        )

    sector_exposure = sum(p.exposure for p in same_sector) + new_exposure
    sector_exposure_limit = capital * risk["max_sector_exposure_pct"] / 100.0
    if sector_exposure > sector_exposure_limit:
        reasons.append(
            f"max_sector_exposure_pct: {candidate.sector} would hold "
            f"{_pct(sector_exposure, capital)}, limit {risk['max_sector_exposure_pct']}%"
        )

    return reasons


def _pct(amount: float, capital: float) -> str:
    return f"{100.0 * amount / capital:.2f}%"
