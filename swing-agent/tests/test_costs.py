"""Transaction costs.

These exist because the first full backtest reported average R -0.026 with no
costs modelled, and Indian round-trip costs are the same order as that number.
Omitting them did not make the answer slightly optimistic; it made it meaningless.
"""
from __future__ import annotations

import copy

import pytest

from src.config import load
from src.risk.costs import CostBreakdown, apply_slippage, round_trip


@pytest.fixture
def cfg():
    return load("config/strategy.yaml")


class TestRoundTrip:
    def test_a_real_position_costs_about_a_quarter_percent(self, cfg):
        """45 shares of BAJFINANCE at 1095 - the live shortlist candidate."""
        c = round_trip(1095.0, 1150.0, 45, cfg)
        assert 0.2 < 100 * c.total / (1095.0 * 45) < 0.35

    def test_zero_quantity_costs_nothing(self, cfg):
        assert round_trip(100.0, 110.0, 0, cfg).total == 0.0

    def test_stt_is_charged_on_both_legs(self, cfg):
        """Delivery equity pays STT buying and selling - not one side."""
        c = round_trip(100.0, 100.0, 100, cfg)
        expected = 10_000 * 0.001 + 10_000 * 0.001
        assert c.stt == pytest.approx(expected)

    def test_stamp_duty_is_buy_side_only(self, cfg):
        buy_only = round_trip(100.0, 200.0, 100, cfg)
        assert buy_only.stamp_duty == pytest.approx(10_000 * 0.00015)

    def test_the_dp_charge_is_per_scrip_not_per_share(self, cfg):
        """Which is why it falls hardest on small positions."""
        small = round_trip(100.0, 105.0, 10, cfg)
        large = round_trip(100.0, 105.0, 1000, cfg)
        assert small.dp == large.dp

    def test_a_tiny_position_is_proportionally_more_expensive(self, cfg):
        """The asymmetry a flat percentage-of-turnover model would miss."""
        tiny = round_trip(100.0, 105.0, 10, cfg)
        big = round_trip(100.0, 105.0, 1000, cfg)
        assert 100 * tiny.total / 1_000 > 100 * big.total / 100_000

    def test_gst_applies_to_fees_not_to_stt(self, cfg):
        """STT is a tax; GST is not charged on it."""
        c = round_trip(100.0, 100.0, 100, cfg)
        assert c.gst == pytest.approx(
            (c.brokerage + c.exchange + c.sebi) * cfg["costs"]["gst_pct"] / 100.0
        )

    def test_total_is_the_sum_of_the_parts(self, cfg):
        c = round_trip(500.0, 550.0, 100, cfg)
        assert c.total == pytest.approx(
            c.brokerage + c.stt + c.exchange + c.sebi + c.stamp_duty + c.gst + c.dp
        )

    def test_costs_scale_with_turnover(self, cfg):
        assert round_trip(100.0, 100.0, 200, cfg).total > round_trip(100.0, 100.0, 100, cfg).total

    def test_flat_brokerage_is_charged_per_order(self, cfg):
        flat = copy.deepcopy(cfg)
        flat["costs"]["brokerage_flat_inr"] = 20.0
        c = round_trip(100.0, 100.0, 100, flat)
        assert c.brokerage == pytest.approx(40.0)      # buy + sell

    def test_the_breakdown_is_readable(self, cfg):
        assert "stt=" in str(round_trip(100.0, 110.0, 100, cfg))


class TestSlippage:
    def test_buys_fill_higher(self, cfg):
        assert apply_slippage(100.0, "buy", cfg) > 100.0

    def test_sells_fill_lower(self, cfg):
        assert apply_slippage(100.0, "sell", cfg) < 100.0

    def test_it_always_moves_against_you(self, cfg):
        """Both directions cost - slippage is never a windfall."""
        assert apply_slippage(100.0, "buy", cfg) - 100.0 == pytest.approx(
            100.0 - apply_slippage(100.0, "sell", cfg)
        )

    def test_zero_slippage_is_a_no_op(self, cfg):
        none = copy.deepcopy(cfg)
        none["costs"]["slippage_pct"] = 0.0
        assert apply_slippage(100.0, "buy", none) == 100.0

    def test_an_unknown_side_is_rejected(self, cfg):
        with pytest.raises(ValueError, match="side"):
            apply_slippage(100.0, "hold", cfg)


class TestNetVersusGross:
    """Net R is the headline; gross exists only to size the drag."""

    def test_net_r_is_below_gross_for_a_winner(self, cfg):
        from src.backtest.engine import Trade
        import pandas as pd

        t = Trade("X", "IT", pd.Timestamp("2024-01-01"), 100.0, 95.0, 100)
        t.exit_price = 110.0
        t.costs = round_trip(100.0, 110.0, 100, cfg)
        assert t.r_multiple < t.gross_r_multiple

    def test_net_r_is_further_below_zero_for_a_loser(self, cfg):
        from src.backtest.engine import Trade
        import pandas as pd

        t = Trade("X", "IT", pd.Timestamp("2024-01-01"), 100.0, 95.0, 100)
        t.exit_price = 95.0
        t.costs = round_trip(100.0, 95.0, 100, cfg)
        assert t.r_multiple < -1.0        # a stop-out costs more than 1R after fees

    def test_costs_make_a_marginal_winner_a_loser(self, cfg):
        """The case that decides whether an edge survives."""
        from src.backtest.engine import Trade
        import pandas as pd

        t = Trade("X", "IT", pd.Timestamp("2024-01-01"), 100.0, 99.0, 100)
        t.exit_price = 100.10          # 10 paise of gross profit per share
        t.costs = round_trip(100.0, 100.10, 100, cfg)
        assert t.gross_r_multiple > 0 and t.r_multiple < 0
