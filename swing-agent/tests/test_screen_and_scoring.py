"""The long screen and the composite ranking, plus the end-to-end path.

The screen tests lean on the fixture verdicts asserted in test_csv_source.py:
if a fixture drifts, that file fails first and names the fixture.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import pandas as pd
from datetime import date

import pytest

from src.config import ConfigError, load
from src.data.csv_source import CsvPriceSource
from src.risk.sizing import Position, portfolio_gates, stop_level
from src.scoring.composite import rank, validate_weights
from src.screens.long_pullback import evaluate

ALL = date(2024, 1, 1), date(2026, 12, 31)


@pytest.fixture
def cfg():
    return load("config/strategy.yaml")


@pytest.fixture
def source(cfg):
    return CsvPriceSource("tests/fixtures", cfg)


@pytest.fixture
def frames(source):
    def get(symbol):
        return source.ohlcv([symbol], *ALL).droplevel("symbol")

    return get


@dataclass
class Candidate:
    symbol: str
    components: dict
    entry: float = 100.0
    stop: float = 95.0
    reason: str = ""


class TestLongScreen:
    def test_the_passing_fixture_passes(self, frames, cfg):
        result = evaluate(frames("PASSING"), "PASSING", cfg, {})
        assert result.passed, result.gate_failures
        assert result.gate_failures == []
        assert result.entry is not None

    def test_the_rsi_fixture_fails_and_says_so(self, frames, cfg):
        result = evaluate(frames("RSIHOT"), "RSIHOT", cfg, {})
        assert not result.passed
        assert len(result.gate_failures) == 1
        assert result.gate_failures[0].startswith("rsi:")

    def test_the_failure_message_carries_the_actual_value(self, frames, cfg):
        result = evaluate(frames("RSIHOT"), "RSIHOT", cfg, {})
        assert "65" in result.gate_failures[0] and "[30, 60]" in result.gate_failures[0]

    def test_every_failing_gate_is_reported_not_just_the_first(self, frames, cfg):
        """SPEC section 8 wants the specific failing condition, plural."""
        result = evaluate(frames("DOWNTREND"), "DOWNTREND", cfg, {})
        assert not result.passed
        assert len(result.gate_failures) >= 3
        named = " ".join(result.gate_failures)
        assert "price_above_sma" in named
        assert "sma_fast_above_slow" in named
        assert "structure" in named

    def test_short_history_is_refused_with_a_reason(self, frames, cfg):
        result = evaluate(frames("PASSING").iloc[:50], "SHORTHIST", cfg, {})
        assert not result.passed
        assert "insufficient history" in result.gate_failures[0]

    def test_confirmations_are_scored_even_on_a_reject(self, frames, cfg):
        """They are diagnostic, not gating - a reject still reports them."""
        result = evaluate(frames("DOWNTREND"), "DOWNTREND", cfg, {})
        assert result.confirmations
        assert all(0.0 <= v <= 1.0 for v in result.confirmations.values())

    def test_confirmations_never_gate(self, frames, cfg):
        """A pass with zero confirmations still passes - it just ranks badly."""
        result = evaluate(frames("PASSING"), "PASSING", cfg, {})
        assert result.passed
        assert set(result.confirmations) >= {
            "stochastic_turning_up",
            "macd_contracting",
            "volume_dryup",
            "volume_expansion",
            "above_anchored_vwap",
            "above_weekly_cpr",
            "relative_strength",
        }

    def test_relative_strength_needs_a_benchmark_and_scores_zero_without_one(
        self, frames, cfg
    ):
        result = evaluate(frames("PASSING"), "PASSING", cfg, {})
        assert result.confirmations["relative_strength"] == 0.0

    def test_relative_strength_is_fractional_across_horizons(self, frames, cfg):
        """PASSING is in a pullback: weak on 1M, strong on 3M vs a flat index.

        That mixed reading is the signature of the setup, and scoring it 0.5
        rather than False keeps it distinguishable from a stock lagging on
        both horizons - which is the opposite kind of candidate.
        """
        df = frames("PASSING")
        flat = df["close"] * 0 + 100.0
        result = evaluate(df, "PASSING", cfg, {"benchmark": flat})
        assert result.confirmations["relative_strength"] == pytest.approx(0.5)

    def test_relative_strength_is_one_when_beating_on_every_horizon(self, frames, cfg):
        df = frames("PASSING")
        falling = df["close"].iloc[0] * (1.0 - 0.002 * pd.Series(
            range(len(df)), index=df.index
        ))
        result = evaluate(df, "PASSING", cfg, {"benchmark": falling})
        assert result.confirmations["relative_strength"] == pytest.approx(1.0)

    def test_the_reason_line_summarises_confirmations(self, frames, cfg):
        result = evaluate(frames("PASSING"), "PASSING", cfg, {})
        assert "confirmations" in result.reason


class TestRanking:
    def test_weights_are_validated(self, cfg):
        broken = copy.deepcopy(cfg)
        broken["scoring"]["weights"] = {"technical_setup": 0.9}
        with pytest.raises(ConfigError, match="sum to 1.0"):
            validate_weights(broken)

    def test_higher_scores_rank_first(self, cfg):
        out = rank(
            [
                Candidate("LOW", {k: 0.2 for k in cfg["scoring"]["weights"]}),
                Candidate("HIGH", {k: 0.9 for k in cfg["scoring"]["weights"]}),
            ],
            cfg,
        )
        assert [c.symbol for c in out] == ["HIGH", "LOW"]

    def test_full_coverage_reports_one(self, cfg):
        out = rank([Candidate("A", {k: 0.5 for k in cfg["scoring"]["weights"]})], cfg)
        assert out[0].coverage == pytest.approx(1.0)
        assert out[0].composite == pytest.approx(0.5)

    def test_a_missing_family_is_renormalised_not_scored_zero(self, cfg):
        """A non-F&O name must not be penalised for a signal it cannot have."""
        full = Candidate("FNO", {k: 0.8 for k in cfg["scoring"]["weights"]})
        without = Candidate(
            "CASH",
            {k: 0.8 for k in cfg["scoring"]["weights"] if k != "futures_confirmation"},
        )
        out = {c.symbol: c for c in rank([full, without], cfg)}
        assert out["CASH"].composite == pytest.approx(out["FNO"].composite)

    def test_scoring_a_missing_family_as_zero_would_have_penalised_it(self, cfg):
        """Shows the bug this avoids, so the test says why it exists."""
        weights = cfg["scoring"]["weights"]
        naive = sum(
            weights[k] * (0.8 if k != "futures_confirmation" else 0.0) for k in weights
        )
        out = rank(
            [
                Candidate(
                    "CASH",
                    {k: 0.8 for k in weights if k != "futures_confirmation"},
                )
            ],
            cfg,
        )
        assert out[0].composite > naive

    def test_coverage_falls_when_families_are_missing(self, cfg):
        out = rank(
            [Candidate("THIN", {"technical_setup": 0.9, "relative_strength": 0.9})], cfg
        )
        assert out[0].coverage == pytest.approx(0.40)
        assert out[0].families_used == ["relative_strength", "technical_setup"]

    def test_min_coverage_suppresses_thin_candidates(self, cfg):
        thin = copy.deepcopy(cfg)
        thin["scoring"]["min_family_coverage"] = 0.6
        out = rank(
            [Candidate("THIN", {"technical_setup": 0.9, "relative_strength": 0.9})], thin
        )
        assert out == []

    def test_a_candidate_with_no_families_is_dropped(self, cfg):
        assert rank([Candidate("EMPTY", {})], cfg) == []

    def test_out_of_range_scores_are_rejected(self, cfg):
        with pytest.raises(ValueError, match="absolute 0..1"):
            rank([Candidate("BAD", {"technical_setup": 1.4})], cfg)

    def test_an_unknown_family_is_rejected(self, cfg):
        with pytest.raises(ConfigError, match="not in scoring.weights"):
            rank([Candidate("BAD", {"vibes": 0.9})], cfg)

    def test_scores_are_not_rescaled_across_the_pool(self, cfg):
        """The best name on a weak day must not score like the best on a strong one."""
        weak = rank([Candidate("W", {k: 0.3 for k in cfg["scoring"]["weights"]})], cfg)
        strong = rank([Candidate("S", {k: 0.9 for k in cfg["scoring"]["weights"]})], cfg)
        assert weak[0].composite == pytest.approx(0.3)
        assert strong[0].composite == pytest.approx(0.9)


class TestEndToEnd:
    """config -> source -> screen -> stop -> gates, on the fixtures."""

    def test_the_full_path_produces_a_populated_result(self, cfg, source):
        df = source.ohlcv(["PASSING"], *ALL).droplevel("symbol")

        result = evaluate(df, "PASSING", cfg, {})
        assert result.passed

        stop = stop_level(df, cfg)
        assert stop is not None and stop < result.entry

        resolved = copy.deepcopy(cfg)
        resolved["risk"]["sector_taxonomy"] = "nse_macro"
        candidate = Position(
            symbol="PASSING", sector="IT", qty=10, entry=result.entry, stop=stop
        )
        assert portfolio_gates([], candidate, resolved) == []

    def test_a_rejected_symbol_never_reaches_the_risk_layer(self, cfg, source):
        df = source.ohlcv(["RSIHOT"], *ALL).droplevel("symbol")
        assert not evaluate(df, "RSIHOT", cfg, {}).passed

    def test_a_stale_symbol_never_reaches_the_screen(self, cfg, source):
        assert source.ohlcv(["STALEBARS"], *ALL).empty
