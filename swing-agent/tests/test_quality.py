"""Bar-quality screening.

The regression case at the bottom is a real bar pulled during the data audit,
kept verbatim so nobody "simplifies" the zero-volume rule away later.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.data.quality import bar_flags, clean_ohlcv

CFG = {
    "drop_zero_volume_bars": True,
    "drop_flat_bars": True,
    "max_stale_bar_pct": 5,
    "min_bars_required": 0,
}


def frame(rows):
    """rows: list of (open, high, low, close, volume)."""
    return pd.DataFrame(
        rows,
        columns=["open", "high", "low", "close", "volume"],
        index=pd.date_range("2024-01-01", periods=len(rows), freq="D"),
    )


GOOD = (100.0, 102.0, 99.0, 101.0, 50_000)


def padded(bad_row, n_good=40):
    """One bad bar among enough good ones to stay under max_stale_bar_pct."""
    return frame([GOOD] * n_good + [bad_row])


class TestFlags:
    def test_clean_bar_raises_no_flags(self):
        assert not bar_flags(frame([GOOD])).any().any()

    def test_zero_volume_flagged(self):
        assert bool(bar_flags(frame([(100.0, 102.0, 99.0, 101.0, 0)]))["zero_volume"].iloc[0])

    def test_flat_bar_flagged(self):
        assert bool(bar_flags(frame([(100.0, 100.0, 100.0, 100.0, 5)]))["flat_bar"].iloc[0])

    @pytest.mark.parametrize(
        "row",
        [
            (100.0, 98.0, 99.0, 99.0, 5),    # high below low
            (100.0, 102.0, 99.0, 103.0, 5),  # close above high
            (100.0, 102.0, 99.0, 98.0, 5),   # close below low
            (98.0, 102.0, 99.0, 101.0, 5),   # open below low
        ],
    )
    def test_internally_inconsistent_bars_flagged(self, row):
        assert bool(bar_flags(frame([row]))["inconsistent"].iloc[0])

    def test_non_positive_price_flagged(self):
        assert bool(bar_flags(frame([(0.0, 102.0, 99.0, 101.0, 5)]))["non_positive_price"].iloc[0])

    def test_negative_volume_flagged(self):
        assert bool(bar_flags(frame([(100.0, 102.0, 99.0, 101.0, -5)]))["negative_volume"].iloc[0])

    def test_nan_field_flagged(self):
        assert bool(bar_flags(frame([(100.0, float("nan"), 99.0, 101.0, 5)]))["nan_field"].iloc[0])

    def test_missing_column_is_rejected(self):
        with pytest.raises(ValueError, match="missing columns"):
            bar_flags(pd.DataFrame({"open": [1.0], "high": [2.0]}))

    def test_flags_do_not_mutate_input(self):
        df = frame([GOOD])
        before = df.copy()
        bar_flags(df)
        pd.testing.assert_frame_equal(df, before)


class TestCleaning:
    def test_clean_series_survives_intact(self):
        df = frame([GOOD] * 10)
        clean, report = clean_ohlcv(df, CFG, "OK")
        assert len(clean) == 10
        assert report.usable and report.dropped_total == 0

    def test_zero_volume_bar_is_dropped(self):
        clean, report = clean_ohlcv(padded((100.0, 102.0, 99.0, 101.0, 0)), CFG)
        assert len(clean) == 40
        assert report.dropped["zero_volume"] == 1

    def test_zero_volume_bar_is_kept_when_the_rule_is_off(self):
        cfg = CFG | {"drop_zero_volume_bars": False}
        clean, _ = clean_ohlcv(padded((100.0, 102.0, 99.0, 101.0, 0)), cfg)
        assert len(clean) == 41

    def test_flat_bar_is_dropped(self):
        clean, report = clean_ohlcv(padded((100.0, 100.0, 100.0, 100.0, 5_000)), CFG)
        assert len(clean) == 40
        assert report.dropped["flat_bar"] == 1

    def test_corrupt_bar_is_dropped_even_with_both_rules_off(self):
        """Inconsistent bars are corrupt, not merely untraded - never optional."""
        cfg = CFG | {"drop_zero_volume_bars": False, "drop_flat_bars": False}
        clean, report = clean_ohlcv(padded((100.0, 98.0, 99.0, 99.0, 5_000)), cfg)
        assert len(clean) == 40
        assert report.dropped["inconsistent"] == 1

    def test_duplicate_timestamps_keep_the_last_republished_bar(self):
        df = frame([GOOD] * 3)
        df.index = [df.index[0], df.index[0], df.index[2]]
        clean, report = clean_ohlcv(df, CFG)
        assert len(clean) == 2
        assert report.dropped["duplicate_index"] == 1

    def test_unsorted_input_comes_back_monotonic(self):
        df = frame([GOOD] * 5).iloc[::-1]
        clean, _ = clean_ohlcv(df, CFG)
        assert clean.index.is_monotonic_increasing

    def test_cfg_must_be_a_mapping(self):
        with pytest.raises(TypeError):
            clean_ohlcv(frame([GOOD]), "data_quality")


class TestUsability:
    """Cleaning is not the point - the verdict is."""

    def test_symbol_is_rejected_when_too_many_bars_are_bad(self):
        df = frame([GOOD] * 9 + [(100.0, 102.0, 99.0, 101.0, 0)])  # 10% stale, limit 5%
        _, report = clean_ohlcv(df, CFG, "JUNK")
        assert not report.usable
        assert "unusable" in report.reasons[0]

    def test_symbol_is_accepted_when_staleness_is_within_the_limit(self):
        df = frame([GOOD] * 99 + [(100.0, 102.0, 99.0, 101.0, 0)])  # 1% stale
        _, report = clean_ohlcv(df, CFG, "FINE")
        assert report.usable

    def test_symbol_is_rejected_when_too_few_clean_bars_remain(self):
        _, report = clean_ohlcv(frame([GOOD] * 10), CFG | {"min_bars_required": 250}, "SHORT")
        assert not report.usable
        assert "need 250" in report.reasons[0]

    def test_both_failures_are_reported_not_just_the_first(self):
        df = frame([GOOD] * 5 + [(100.0, 102.0, 99.0, 101.0, 0)] * 5)
        _, report = clean_ohlcv(df, CFG | {"min_bars_required": 250}, "BAD")
        assert len(report.reasons) == 2

    def test_stale_pct_on_an_empty_frame_does_not_divide_by_zero(self):
        _, report = clean_ohlcv(frame([]), CFG, "EMPTY")
        assert report.stale_pct == 0.0

    def test_report_str_names_the_symbol_and_the_verdict(self):
        df = frame([GOOD] * 9 + [(100.0, 102.0, 99.0, 101.0, 0)])
        _, report = clean_ohlcv(df, CFG, "JUNK")
        assert "JUNK" in str(report) and "REJECTED" in str(report)


class TestRegressionRealBar:
    """RELIANCE.BSE 2026-06-26, as returned by Alpha Vantage during the audit.

    o=h=l=c=1318.25, volume=0. Neighbours are the genuine 06-25 and 06-29 bars.
    """

    ROWS = [
        (1316.05, 1327.70, 1314.05, 1318.25, 2_028_547),  # 2026-06-25
        (1318.25, 1318.25, 1318.25, 1318.25, 0),          # 2026-06-26  carried forward
        (1306.30, 1314.00, 1293.00, 1300.85, 649_738),    # 2026-06-29
    ]

    def test_the_carried_forward_bar_is_removed(self):
        clean, report = clean_ohlcv(frame(self.ROWS), CFG | {"max_stale_bar_pct": 50}, "RELIANCE")
        assert len(clean) == 2
        assert report.dropped["zero_volume"] == 1
        assert report.dropped["flat_bar"] == 1

    def test_true_range_is_zero_on_that_bar_which_is_why_it_must_go(self):
        df = frame(self.ROWS)
        bar = df.iloc[1]
        assert bar["high"] - bar["low"] == 0.0

    def test_the_real_neighbouring_bars_are_untouched(self):
        clean, _ = clean_ohlcv(frame(self.ROWS), CFG | {"max_stale_bar_pct": 50}, "RELIANCE")
        assert list(clean["volume"]) == [2_028_547, 649_738]
