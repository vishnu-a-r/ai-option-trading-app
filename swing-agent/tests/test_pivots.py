"""swing_points() is the foundation for all structure detection - test it hard.

Fixtures are hand-built so every expected pivot is verifiable by reading the
series, not by trusting the implementation that produced it.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.indicators.pivots import confirmed_as_of, swing_points


def frame(highs, lows=None):
    """OHLCV frame from a high series; lows mirror unless given explicitly."""
    lows = lows if lows is not None else [h - 1 for h in highs]
    return pd.DataFrame(
        {"high": highs, "low": lows},
        index=pd.date_range("2024-01-01", periods=len(highs), freq="D"),
    )


def kinds(pivots, kind):
    return pivots[pivots["kind"] == kind]


class TestBasicDetection:
    def test_single_peak_is_found(self):
        #        0  1  2  3  4
        df = frame([1, 2, 5, 2, 1])
        highs = kinds(swing_points(df, lookback=2), "high")
        assert list(highs["bar"]) == [2]
        assert list(highs["price"]) == [5.0]

    def test_single_trough_is_found(self):
        df = frame([9, 9, 9, 9, 9], lows=[5, 4, 1, 4, 5])
        lows = kinds(swing_points(df, lookback=2), "low")
        assert list(lows["bar"]) == [2]
        assert list(lows["price"]) == [1.0]

    def test_lookback_one_finds_more_pivots_than_lookback_two(self):
        highs = [1, 3, 2, 4, 2, 5, 1, 6, 2]
        wide = len(kinds(swing_points(frame(highs), 2), "high"))
        narrow = len(kinds(swing_points(frame(highs), 1), "high"))
        assert narrow >= wide

    def test_monotonic_series_has_no_pivots(self):
        assert swing_points(frame(list(range(1, 30))), lookback=3).empty

    def test_highs_and_lows_are_both_returned(self):
        df = frame([1, 2, 5, 2, 1, 2, 5, 2, 1], lows=[9, 8, 7, 8, 3, 8, 7, 8, 9])
        piv = swing_points(df, lookback=2)
        assert set(piv["kind"]) == {"high", "low"}

    def test_result_is_sorted_by_bar(self):
        df = frame([1, 4, 1, 4, 1, 4, 1, 4, 1, 4, 1])
        piv = swing_points(df, lookback=1)
        assert list(piv["bar"]) == sorted(piv["bar"])


class TestLookahead:
    """The bias that quietly flatters every backtest entry price."""

    def test_no_pivot_in_the_trailing_lookback_window(self):
        # A peak at the very end looks like a pivot but is not yet confirmed.
        df = frame([1, 2, 3, 4, 9])
        assert swing_points(df, lookback=2).empty

    def test_confirmed_at_is_lookback_bars_after_the_pivot(self):
        df = frame([1, 2, 5, 2, 1, 1, 1])
        piv = swing_points(df, lookback=2)
        row = piv.iloc[0]
        assert row["bar"] == 2
        assert row["confirmed_at_bar"] == 4
        assert row["confirmed_at_date"] == df.index[4]

    def test_confirmed_as_of_hides_the_pivot_until_its_confirmation_bar(self):
        df = frame([1, 2, 5, 2, 1, 1, 1])
        piv = swing_points(df, lookback=2)
        assert confirmed_as_of(piv, bar=3).empty      # peak has printed, not yet knowable
        assert len(confirmed_as_of(piv, bar=4)) == 1  # now it is

    def test_confirmed_as_of_on_empty_input_is_empty(self):
        assert confirmed_as_of(swing_points(frame([1, 2, 3]), 1), bar=99).empty


class TestTies:
    """Equal highs are common on low tick sizes; the rule must be deterministic."""

    def test_plateau_yields_exactly_one_pivot_at_its_last_bar(self):
        #        0  1  2  3  4  5
        df = frame([1, 5, 5, 1, 1, 1])
        highs = kinds(swing_points(df, lookback=1), "high")
        assert list(highs["bar"]) == [2]

    def test_plateau_trough_yields_exactly_one_pivot_at_its_last_bar(self):
        df = frame([9] * 6, lows=[8, 2, 2, 8, 8, 8])
        lows = kinds(swing_points(df, lookback=1), "low")
        assert list(lows["bar"]) == [2]

    def test_wide_plateau_still_yields_one_pivot(self):
        df = frame([1, 5, 5, 5, 5, 1, 1, 1])
        highs = kinds(swing_points(df, lookback=1), "high")
        assert len(highs) == 1


class TestEdgeCases:
    def test_series_shorter_than_the_window_returns_empty_not_error(self):
        out = swing_points(frame([1, 2, 3, 4]), lookback=2)
        assert out.empty

    def test_empty_result_still_carries_the_full_schema(self):
        out = swing_points(frame([1, 2, 3, 4]), lookback=2)
        assert list(out.columns) == [
            "bar", "date", "price", "kind", "confirmed_at_bar", "confirmed_at_date",
        ]

    def test_exact_minimum_length_is_accepted(self):
        df = frame([1, 5, 1])  # 2*1+1
        assert len(kinds(swing_points(df, lookback=1), "high")) == 1

    @pytest.mark.parametrize("bad", [0, -1])
    def test_non_positive_lookback_is_rejected(self, bad):
        with pytest.raises(ValueError, match="lookback"):
            swing_points(frame([1, 2, 3]), lookback=bad)

    def test_missing_column_is_rejected(self):
        df = pd.DataFrame({"high": [1, 2, 3]})
        with pytest.raises(ValueError, match="low"):
            swing_points(df, lookback=1)


class TestStructureUseCase:
    """What is_uptrend_structure() will actually ask of this."""

    def test_ascending_peaks_come_back_in_ascending_order(self):
        # First peak sits at bar 2: with lookback=2 a pivot needs two bars each side.
        highs = [1, 1, 3, 1, 1, 5, 1, 1, 7, 1, 1, 1]
        peaks = kinds(swing_points(frame(highs), lookback=2), "high")
        assert list(peaks["price"]) == [3.0, 5.0, 7.0]

    def test_descending_troughs_come_back_in_descending_order(self):
        lows = [9, 9, 7, 9, 9, 5, 9, 9, 3, 9, 9, 9]
        troughs = kinds(swing_points(frame([20] * len(lows), lows), lookback=2), "low")
        assert list(troughs["price"]) == [7.0, 5.0, 3.0]
