"""Stops and portfolio gates.

Two tests here guard decisions rather than arithmetic: that stop_level refuses
instead of falling back on a percentage, and that portfolio_gates raises while
the sector taxonomy is null instead of skipping the sector caps.
"""
from __future__ import annotations

import copy
from datetime import date

import pandas as pd
import pytest

from src.config import UnresolvedConfig, load
from src.data.csv_source import CsvPriceSource
from src.risk.sizing import (
    Position,
    portfolio_gates,
    position_size,
    size_with_reason,
    stop_level,
)


@pytest.fixture
def cfg():
    return load("config/strategy.yaml")


@pytest.fixture
def resolved(cfg):
    """Config with a taxonomy pinned, so the sector caps can be exercised."""
    out = copy.deepcopy(cfg)
    out["risk"]["sector_taxonomy"] = "nse_macro"
    return out


@pytest.fixture
def passing(cfg):
    src = CsvPriceSource("tests/fixtures", cfg)
    return src.ohlcv(["PASSING"], date(2024, 1, 1), date(2026, 12, 31)).droplevel("symbol")


def pos(symbol="X", sector="IT", qty=100, entry=100.0, stop=95.0):
    return Position(symbol=symbol, sector=sector, qty=qty, entry=entry, stop=stop)


class TestPosition:
    def test_exposure_is_qty_times_entry(self):
        assert pos(qty=100, entry=250.0).exposure == 25_000

    def test_risk_amount_is_the_distance_to_the_stop(self):
        assert pos(qty=100, entry=100.0, stop=95.0).risk_amount == 500


class TestStopLevel:
    def test_stop_sits_below_the_last_confirmed_swing_low(self, passing, cfg):
        stop = stop_level(passing, cfg)
        assert stop is not None and stop < passing["close"].iloc[-1]

    def test_the_buffer_widens_the_stop(self, passing, cfg):
        wide = copy.deepcopy(cfg)
        wide["risk"]["atr_stop_buffer"] = 2.0
        assert stop_level(passing, wide) < stop_level(passing, cfg)

    def test_zero_buffer_puts_the_stop_at_the_swing_low(self, passing, cfg):
        from src.indicators.pivots import confirmed_as_of, swing_points

        bare = copy.deepcopy(cfg)
        bare["risk"]["atr_stop_buffer"] = 0.0
        pivots = confirmed_as_of(
            swing_points(passing, cfg["long_pullback"]["trend"]["pivot_lookback"]),
            len(passing) - 1,
        )
        last_low = pivots[pivots["kind"] == "low"]["price"].iloc[-1]
        assert stop_level(passing, bare) == pytest.approx(last_low)

    def test_no_confirmed_pivot_means_no_stop_not_a_percentage(self, cfg):
        """The guard. A 2% fallback here would look like defensive programming.

        It would sit inside one day's normal range for most Nifty 500 midcaps,
        producing a stop swept on noise precisely where structure was hardest
        to read.
        """
        flat = pd.DataFrame(
            {
                "open": [100.0] * 30,
                "high": [101.0] * 30,
                "low": [99.0] * 30,
                "close": [100.0] * 30,
                "volume": [1000] * 30,
            },
            index=pd.date_range("2024-01-01", periods=30, freq="D"),
        )
        assert stop_level(flat, cfg) is None

    def test_too_short_a_history_means_no_stop(self, passing, cfg):
        assert stop_level(passing.iloc[:10], cfg) is None

    def test_as_of_bar_does_not_read_the_future(self, passing, cfg):
        cursor = 200
        assert stop_level(passing, cfg, as_of_bar=cursor) == pytest.approx(
            stop_level(passing.iloc[: cursor + 1], cfg)
        )


class TestPositionSize:
    """Implemented from the risk block once it was confirmed no Excel exists.

    The invariant these protect: rupee risk is FIXED and quantity is derived.
    Two setups of equal conviction carry equal risk regardless of stop
    distance - unless the concentration cap truncates, which is intended and
    must be reported rather than silently absorbed.
    """

    CAPITAL = 200_000

    def test_quantity_is_derived_from_fixed_rupee_risk(self, cfg):
        # Rs 2,000 risk / Rs 71.09 per share = 28 shares.
        assert position_size(381.60, 310.51, self.CAPITAL, cfg) == 28

    def test_equal_conviction_carries_equal_rupee_risk(self, cfg):
        """The invariant the whole block exists to protect."""
        wide = position_size(400.0, 350.0, self.CAPITAL, cfg)     # Rs 50 stop
        wider = position_size(400.0, 300.0, self.CAPITAL, cfg)    # Rs 100 stop
        assert wide * 50 == pytest.approx(2000, abs=50)
        assert wider * 100 == pytest.approx(2000, abs=100)

    def test_a_tighter_stop_gives_a_larger_position(self, cfg):
        tight = position_size(400.0, 396.0, self.CAPITAL, cfg)
        loose = position_size(400.0, 360.0, self.CAPITAL, cfg)
        assert tight > loose

    def test_the_concentration_cap_truncates_and_says_so(self, cfg):
        qty, why = size_with_reason(100.0, 99.5, self.CAPITAL, cfg)
        assert qty * 100.0 <= self.CAPITAL * cfg["risk"]["max_position_pct_of_capital"] / 100
        assert "truncated" in why and "effective risk" in why

    def test_a_truncated_position_carries_less_than_full_risk(self, cfg):
        """Intended, not a bug - but it must be visible."""
        qty, why = size_with_reason(100.0, 99.5, self.CAPITAL, cfg)
        assert qty * 0.5 < self.CAPITAL * cfg["risk"]["risk_per_trade_pct"] / 100
        assert why is not None

    def test_an_untruncated_position_reports_no_reason(self, cfg):
        _, why = size_with_reason(381.60, 310.51, self.CAPITAL, cfg)
        assert why is None

    def test_the_cap_is_applied_after_the_formula_not_before(self, cfg):
        """Order does not commute. Cap first would make risk an OUTPUT of size."""
        qty, _ = size_with_reason(100.0, 99.5, self.CAPITAL, cfg)
        cap_qty = int(self.CAPITAL * cfg["risk"]["max_position_pct_of_capital"] / 100 / 100.0)
        assert qty == cap_qty          # cap won, having truncated a larger number
        assert qty < 2000 / 0.5        # ...which the formula alone would have produced

    def test_a_stop_at_or_above_entry_is_no_trade(self, cfg):
        assert position_size(100.0, 100.0, self.CAPITAL, cfg) == 0
        assert position_size(100.0, 105.0, self.CAPITAL, cfg) == 0

    def test_an_unaffordable_share_is_no_trade(self, cfg):
        """One share above the 25% cap cannot be bought at all."""
        qty, why = size_with_reason(80_000.0, 79_000.0, self.CAPITAL, cfg)
        assert qty == 0 and "exceeds" in why

    def test_whole_shares_only(self, cfg):
        assert isinstance(position_size(1095.0, 1058.70, self.CAPITAL, cfg), int)

    def test_non_positive_entry_is_rejected(self, cfg):
        with pytest.raises(ValueError, match="entry"):
            position_size(0.0, -1.0, self.CAPITAL, cfg)


class TestSectorTaxonomyGuard:
    def test_gates_run_now_that_a_taxonomy_is_pinned(self, cfg):
        assert portfolio_gates([], pos(qty=10), cfg) == []

    def test_gates_still_raise_if_it_is_ever_unset(self, cfg):
        """The guard has to keep working if someone nulls it again."""
        import copy

        unset = copy.deepcopy(cfg)
        unset["risk"]["sector_taxonomy"] = None
        with pytest.raises(UnresolvedConfig, match="sector_taxonomy"):
            portfolio_gates([], pos(), unset)


class TestPortfolioGates:
    def test_a_small_first_position_passes_everything(self, resolved):
        assert portfolio_gates([], pos(qty=10, entry=100.0, stop=95.0), resolved) == []

    def test_position_count_cap_fires(self, resolved):
        open_positions = [pos(symbol=f"S{i}", sector=f"SEC{i}", qty=1) for i in range(6)]
        reasons = portfolio_gates(open_positions, pos(sector="NEW", qty=1), resolved)
        assert any("max_concurrent_positions" in r for r in reasons)

    def test_aggregate_risk_cap_fires(self, resolved):
        """Six full-risk positions is the budget; the seventh is refused."""
        full = [pos(symbol=f"S{i}", sector=f"SEC{i}", qty=400, entry=100.0, stop=95.0)
                for i in range(5)]  # 5 x Rs 2,000 = Rs 10,000 = 5%
        reasons = portfolio_gates(
            full, pos(sector="NEW", qty=800, entry=100.0, stop=95.0), resolved  # +2%
        )
        assert any("max_aggregate_open_risk_pct" in r for r in reasons)

    def test_deployed_capital_cap_fires_when_risk_alone_would_not(self, resolved):
        """The gap that dropping shorts exposed.

        Five tight-stop positions at 20% of capital each: Rs 200,000 deployed
        against Rs 200,000 capital, but only about 2% aggregate risk - well
        inside the 6% cap. Cash is the binding constraint, not risk.
        """
        tight = [
            pos(symbol=f"S{i}", sector=f"SEC{i}", qty=400, entry=100.0, stop=99.0)
            for i in range(5)
        ]
        candidate = pos(sector="NEW", qty=400, entry=100.0, stop=99.0)

        open_risk = sum(p.risk_amount for p in tight) + candidate.risk_amount
        assert open_risk < 200_000 * 0.06  # risk cap would NOT catch this

        reasons = portfolio_gates(tight, candidate, resolved)
        assert any("max_deployed_pct_of_capital" in r for r in reasons)
        assert not any("max_aggregate_open_risk_pct" in r for r in reasons)

    def test_sector_risk_cap_fires_on_the_third_full_risk_name(self, resolved):
        same = [pos(symbol=f"S{i}", sector="BANKING", qty=400, entry=100.0, stop=95.0)
                for i in range(2)]  # 2 x 1% = 2%, at the limit
        reasons = portfolio_gates(
            same, pos(sector="BANKING", qty=400, entry=100.0, stop=95.0), resolved
        )
        assert any("max_sector_risk_pct" in r for r in reasons)

    def test_a_different_sector_is_not_blocked_by_that(self, resolved):
        same = [pos(symbol=f"S{i}", sector="BANKING", qty=400, entry=100.0, stop=95.0)
                for i in range(2)]
        reasons = portfolio_gates(
            same, pos(sector="IT", qty=400, entry=100.0, stop=95.0), resolved
        )
        assert not any("max_sector" in r for r in reasons)

    def test_sector_exposure_cap_fires(self, resolved):
        same = [pos(symbol="A", sector="IT", qty=400, entry=100.0, stop=99.5)]  # 20%
        reasons = portfolio_gates(
            same, pos(sector="IT", qty=500, entry=100.0, stop=99.5), resolved  # +25% = 45%
        )
        assert any("max_sector_exposure_pct" in r for r in reasons)

    def test_every_firing_reason_is_returned_not_just_the_first(self, resolved):
        """The report has to name the specific gate; "capped" is not an answer."""
        crowded = [
            pos(symbol=f"S{i}", sector="BANKING", qty=500, entry=100.0, stop=95.0)
            for i in range(6)
        ]
        reasons = portfolio_gates(
            crowded, pos(sector="BANKING", qty=500, entry=100.0, stop=95.0), resolved
        )
        assert len(reasons) >= 4

    def test_reasons_name_the_cap_and_the_number(self, resolved):
        crowded = [pos(symbol=f"S{i}", sector=f"SEC{i}", qty=1) for i in range(6)]
        reasons = portfolio_gates(crowded, pos(sector="NEW", qty=1), resolved)
        assert "6 open" in reasons[0] and "limit 6" in reasons[0]
