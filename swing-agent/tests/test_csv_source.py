"""CsvPriceSource and the fixtures.

The fixture assertions here are the contract the screen tests rely on: if a
fixture stops landing on its intended gate, these fail before the screen tests
do, and the failure says which fixture drifted rather than which screen broke.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.config import load
from src.data.csv_source import CsvPriceSource
from src.indicators.momentum import rsi
from src.indicators.trend import is_uptrend_structure, sma

FIXTURES = "tests/fixtures"
ALL = date(2024, 1, 1), date(2026, 12, 31)


@pytest.fixture
def cfg():
    return load("config/strategy.yaml")


@pytest.fixture
def source(cfg):
    return CsvPriceSource(FIXTURES, cfg)


class TestProtocolConformance:
    def test_bad_directory_is_rejected(self, cfg):
        with pytest.raises(ValueError, match="not a directory"):
            CsvPriceSource("tests/fixtures/PASSING.csv", cfg)

    def test_ohlcv_returns_a_symbol_date_multiindex(self, source):
        out = source.ohlcv(["PASSING"], *ALL)
        assert out.index.names == ["symbol", "date"]
        assert list(out.columns) == ["open", "high", "low", "close", "volume"]

    def test_multiple_symbols_come_back_together(self, source):
        out = source.ohlcv(["PASSING", "RSIHOT"], *ALL)
        assert set(out.index.get_level_values("symbol")) == {"PASSING", "RSIHOT"}

    def test_unknown_symbol_is_skipped_not_an_error(self, source):
        assert source.ohlcv(["NOSUCHSYMBOL"], *ALL).empty

    def test_empty_result_still_has_the_right_shape(self, source):
        out = source.ohlcv(["NOSUCHSYMBOL"], *ALL)
        assert out.index.names == ["symbol", "date"]

    def test_date_window_is_honoured(self, source):
        out = source.ohlcv(["PASSING"], date(2024, 1, 1), date(2024, 1, 31))
        assert len(out) == 31

    def test_non_daily_interval_is_rejected(self, source):
        with pytest.raises(ValueError, match="daily bars only"):
            source.ohlcv(["PASSING"], *ALL, interval="1h")

    def test_delivery_pct_refuses_rather_than_returning_empty(self, source):
        """An empty frame would let the institutional layer score a silent zero."""
        with pytest.raises(NotImplementedError, match="no source"):
            source.delivery_pct(["PASSING"], *ALL)


class TestQualityIntegration:
    def test_a_stale_symbol_is_excluded_entirely(self, source):
        assert source.ohlcv(["STALEBARS"], *ALL).empty

    def test_the_exclusion_is_explained_not_silent(self, source):
        source.ohlcv(["STALEBARS"], *ALL)
        report = source.reports["STALEBARS"]
        assert not report.usable
        assert report.dropped["zero_volume"] > 0
        assert "unusable" in report.reasons[0]

    def test_a_clean_symbol_keeps_all_its_bars(self, source):
        source.ohlcv(["PASSING"], *ALL)
        assert source.reports["PASSING"].dropped_total == 0

    def test_stale_symbol_drops_out_of_a_mixed_request(self, source):
        out = source.ohlcv(["PASSING", "STALEBARS"], *ALL)
        assert set(out.index.get_level_values("symbol")) == {"PASSING"}


class TestFixtureVerdicts:
    """Each fixture must still land where it was built to land."""

    def frame(self, source, symbol):
        return source.ohlcv([symbol], *ALL).droplevel("symbol")

    def gates(self, df, cfg):
        lp = cfg["long_pullback"]
        close = df["close"]
        s50 = sma(close, lp["trend"]["price_above_sma"]).iloc[-1]
        fast, slow = lp["trend"]["sma_fast_above_slow"]
        r = rsi(close, lp["momentum"]["rsi_period"]).iloc[-1]
        failures = []
        if not close.iloc[-1] > s50:
            failures.append("price_above_sma")
        if not sma(close, fast).iloc[-1] > sma(close, slow).iloc[-1]:
            failures.append("sma_fast_above_slow")
        if not is_uptrend_structure(
            df, lp["trend"]["pivot_lookback"], lp["trend"]["min_swing_points"]
        ):
            failures.append("structure")
        if not lp["momentum"]["rsi_min"] <= r <= lp["momentum"]["rsi_max"]:
            failures.append("rsi")
        return failures, r

    def test_passing_fixture_fails_nothing(self, source, cfg):
        failures, _ = self.gates(self.frame(source, "PASSING"), cfg)
        assert failures == []

    def test_passing_rsi_sits_mid_band_not_on_an_edge(self, source, cfg):
        """A fixture parked at 30.1 would flip on any smoothing change."""
        _, r = self.gates(self.frame(source, "PASSING"), cfg)
        assert 35 < r < 55

    def test_rsihot_fails_only_on_rsi(self, source, cfg):
        """Single-gate isolation: proves the RSI gate is what rejected it."""
        failures, r = self.gates(self.frame(source, "RSIHOT"), cfg)
        assert failures == ["rsi"]
        assert r > cfg["long_pullback"]["momentum"]["rsi_max"]

    def test_downtrend_fails_the_trend_and_structure_gates(self, source, cfg):
        failures, _ = self.gates(self.frame(source, "DOWNTREND"), cfg)
        assert {"price_above_sma", "sma_fast_above_slow", "structure"} <= set(failures)

    def test_every_fixture_has_enough_bars_for_a_200_sma(self, source, cfg):
        for symbol in ["PASSING", "RSIHOT", "DOWNTREND"]:
            df = self.frame(source, symbol)
            assert len(df) >= cfg["data_quality"]["min_bars_required"]
