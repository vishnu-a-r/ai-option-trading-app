"""Fundamental gate.

This family carries 0.30 of the composite weight and has never contributed to a
signal or a backtest, because no data source exists (DATA_AUDIT.md §4). These
tests use a calibrated config fixture to exercise logic that the real config
cannot yet run.
"""
from __future__ import annotations

import copy

import pandas as pd
import pytest

from src.config import UnresolvedConfig, load
from src.screens.fundamental import applicable_thresholds, gate, score


@pytest.fixture
def cfg():
    return load("config/strategy.yaml")


@pytest.fixture
def calibrated(cfg):
    """A config with thresholds filled in - for testing logic only.

    These numbers are NOT a calibration and must never be copied into
    strategy.yaml. Real ones come from percentiles of the actual distribution.
    """
    out = copy.deepcopy(cfg)
    out["fundamental"]["long_gate"] = {
        "min_roce": 15.0,
        "min_roe": 12.0,
        "max_debt_to_equity": 1.0,
        "min_ocf_to_pat": 0.8,
        "max_promoter_pledge_pct": 10.0,
        "revenue_growth_3y_min": 8.0,
    }
    out["fundamental"]["sector_overrides"]["BANKING"]["thresholds"] = {
        "min_roa": 1.0,
        "min_net_interest_margin": 3.0,
        "max_gross_npa_pct": 4.0,
        "min_capital_adequacy_pct": 12.0,
    }
    return out


def strong():
    return pd.Series({
        "roce": 22.0, "roe": 18.0, "debt_to_equity": 0.4,
        "ocf_to_pat": 1.1, "promoter_pledge_pct": 0.0, "revenue_growth_3y": 15.0,
    })


def weak():
    return pd.Series({
        "roce": 8.0, "roe": 6.0, "debt_to_equity": 2.5,
        "ocf_to_pat": 0.4, "promoter_pledge_pct": 35.0, "revenue_growth_3y": 1.0,
    })


class TestNullsBlock:
    """The live config cannot run this gate, and that is the correct state."""

    def test_the_real_config_blocks_rather_than_passing(self, cfg):
        reasons = gate("X", "Diversified", strong(), cfg)
        assert reasons and "null" in reasons[0]

    def test_a_strong_stock_is_still_blocked(self, cfg):
        """Uncalibrated must not mean permissive."""
        assert gate("X", "Diversified", strong(), cfg) != []

    def test_banking_thresholds_are_also_null(self, cfg):
        with pytest.raises(UnresolvedConfig):
            applicable_thresholds("BANKING", cfg)

    def test_missing_symbol_data_blocks(self, cfg):
        assert gate("X", "Diversified", None, cfg) == [
            "fundamental: no data for this symbol"
        ]


class TestSectorMetricSets:
    """Overrides change which metrics apply, not just their values."""

    def test_banking_drops_debt_to_equity(self, calibrated):
        keys = applicable_thresholds("BANKING", calibrated)
        assert "max_debt_to_equity" not in keys

    def test_banking_drops_roce_and_ocf_quality(self, calibrated):
        keys = applicable_thresholds("BANKING", calibrated)
        assert "min_roce" not in keys and "min_ocf_to_pat" not in keys

    def test_banking_adds_lender_specific_metrics(self, calibrated):
        keys = applicable_thresholds("BANKING", calibrated)
        assert {"min_roa", "max_gross_npa_pct", "min_capital_adequacy_pct"} <= set(keys)

    def test_nbfc_keeps_debt_to_equity_at_its_own_level(self, calibrated):
        """Leverage applies to an NBFC, just not at a manufacturer's threshold."""
        calibrated["fundamental"]["sector_overrides"]["NBFC"]["thresholds"] = {
            "min_roa": 1.5, "max_gross_npa_pct": 5.0,
            "min_capital_adequacy_pct": 15.0, "max_debt_to_equity": 6.0,
        }
        keys = applicable_thresholds("NBFC", calibrated)
        assert keys["max_debt_to_equity"] == 6.0

    def test_an_unlisted_sector_gets_the_generic_set(self, calibrated):
        keys = applicable_thresholds("Diversified", calibrated)
        assert set(keys) == set(calibrated["fundamental"]["long_gate"])

    def test_the_result_records_what_was_excluded(self, calibrated):
        banking = pd.Series({
            "roa": 1.5, "net_interest_margin": 3.5,
            "gross_npa_pct": 2.0, "capital_adequacy_pct": 16.0,
        })
        result = score("BANK", "BANKING", banking, calibrated)
        assert "max_debt_to_equity" in result.metrics_excluded


class TestScoring:
    def test_a_strong_stock_passes_and_scores_high(self, calibrated):
        result = score("GOOD", "Diversified", strong(), calibrated)
        assert result.passed and result.score > 60

    def test_a_weak_stock_fails_every_metric(self, calibrated):
        result = score("BAD", "Diversified", weak(), calibrated)
        assert not result.passed and len(result.failures) == 6

    def test_failures_name_the_value_and_the_limit(self, calibrated):
        result = score("BAD", "Diversified", weak(), calibrated)
        assert any("2.50" in f and "1.0" in f for f in result.failures)

    def test_floors_and_ceilings_run_in_opposite_directions(self, calibrated):
        """High ROCE is good; high debt is not."""
        high_debt = strong().copy()
        high_debt["debt_to_equity"] = 5.0
        result = score("X", "Diversified", high_debt, calibrated)
        assert result.components["debt_to_equity"] < result.components["roce"]

    def test_a_missing_metric_is_a_failure_not_a_pass(self, calibrated):
        """Gating on fundamentals with no fundamentals must refuse."""
        partial = strong().drop("roce")
        result = score("X", "Diversified", partial, calibrated)
        assert any("roce: not available" in f for f in result.failures)
        assert result.components["roce"] == 0.0

    def test_the_breakdown_is_never_a_single_opaque_number(self, calibrated):
        result = score("GOOD", "Diversified", strong(), calibrated)
        assert len(result.components) == 6

    def test_score_stays_within_zero_and_one_hundred(self, calibrated):
        extreme = strong().copy()
        extreme["roce"] = 500.0
        result = score("X", "Diversified", extreme, calibrated)
        assert 0.0 <= result.score <= 100.0

    def test_a_threshold_with_no_declared_direction_is_rejected(self, calibrated):
        """A new threshold that is neither a floor nor a ceiling cannot be scored."""
        calibrated["fundamental"]["long_gate"]["mystery_metric"] = 5.0
        with pytest.raises(ValueError, match="neither FLOORS nor CEILINGS"):
            score("X", "Diversified", strong(), calibrated)
