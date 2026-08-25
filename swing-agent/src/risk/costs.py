"""Transaction costs for Indian delivery equity.

Kept separate from sizing because these do not change position size - they
change what a position RETURNS. Sizing risks a fixed rupee amount against the
stop; costs are subtracted from the result afterwards.

WHY THIS EXISTS. The first full backtest reported an average R of -0.026 with
no costs modelled. Indian round-trip costs on delivery equity land around
0.1-0.3% of position value, which against a typical 5% stop distance is roughly
0.02-0.06 R. The costs are the same size as the measured edge, so omitting them
does not make the answer slightly optimistic - it makes it meaningless.

Every omitted cost biases a backtest the same way: upward.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostBreakdown:
    """Rupee costs of one round trip, itemised so the total can be interrogated."""

    brokerage: float = 0.0
    stt: float = 0.0
    exchange: float = 0.0
    sebi: float = 0.0
    stamp_duty: float = 0.0
    gst: float = 0.0
    dp: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.brokerage + self.stt + self.exchange + self.sebi
            + self.stamp_duty + self.gst + self.dp
        )

    def __str__(self) -> str:
        parts = [
            f"{name}={value:.2f}"
            for name, value in [
                ("brokerage", self.brokerage), ("stt", self.stt),
                ("exchange", self.exchange), ("sebi", self.sebi),
                ("stamp", self.stamp_duty), ("gst", self.gst), ("dp", self.dp),
            ]
            if value
        ]
        return f"total={self.total:.2f} [{', '.join(parts)}]"


def round_trip(entry: float, exit_price: float, qty: int, cfg: dict) -> CostBreakdown:
    """Full buy-then-sell cost in rupees.

    Note which side each charge applies to - they are not symmetric. STT is
    charged on both legs for delivery, stamp duty only on the buy, and the DP
    charge only on the sell and per scrip rather than per share, so it falls
    hardest on small positions. That last asymmetry is why a Rs 5,000 position
    can be uneconomic while a Rs 50,000 one is fine, and a backtest that models
    costs as a flat percentage of turnover misses it entirely.
    """
    if qty <= 0:
        return CostBreakdown()

    costs = cfg["costs"]
    buy_value = entry * qty
    sell_value = exit_price * qty
    turnover = buy_value + sell_value

    brokerage = (
        turnover * costs["brokerage_pct"] / 100.0
        + 2 * costs["brokerage_flat_inr"]          # one per executed order
    )
    stt = (
        buy_value * costs["stt_buy_pct"] / 100.0
        + sell_value * costs["stt_sell_pct"] / 100.0
    )
    exchange = turnover * costs["exchange_txn_pct"] / 100.0
    sebi = turnover * costs["sebi_turnover_pct"] / 100.0
    stamp = buy_value * costs["stamp_duty_buy_pct"] / 100.0
    gst = (brokerage + exchange + sebi) * costs["gst_pct"] / 100.0
    dp = costs["dp_charge_sell_inr"]               # per scrip, not per share

    return CostBreakdown(
        brokerage=brokerage, stt=stt, exchange=exchange, sebi=sebi,
        stamp_duty=stamp, gst=gst, dp=dp,
    )


def apply_slippage(price: float, side: str, cfg: dict) -> float:
    """Move a modelled fill against you.

    Buys fill higher and sells fill lower than the price the simulation saw.
    Applied to the price rather than added as a fee, because that is what
    slippage is - and because it then flows into the risk-per-share figure,
    which a fee would not.
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    slip = cfg["costs"]["slippage_pct"] / 100.0
    return price * (1.0 + slip) if side == "buy" else price * (1.0 - slip)
