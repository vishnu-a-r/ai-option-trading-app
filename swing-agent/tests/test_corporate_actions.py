"""Corporate action detection and back-adjustment.

Two of these pin bugs found while building this, both of which produced
confident wrong answers rather than obvious failures.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.config import load
from src.data.corporate_actions import CLEAN_RATIOS, adjust, detect, summarise


@pytest.fixture
def cfg():
    return load("config/strategy.yaml")


def series(values, start="2024-01-01", freq="B"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq=freq))


def frame(closes, start="2024-01-01"):
    idx = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "open": closes, "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes], "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


class TestDetection:
    def test_a_one_for_one_bonus_is_detected(self, cfg):
        """RELIANCE 2024-10-28: 2655.70 -> 1334.35, observed 0.5024."""
        events = detect(series([2679.6, 2655.7, 1334.35, 1340.0]), cfg)
        assert len(events) == 1
        assert events[0].adjustable
        assert events[0].factor == pytest.approx(0.5)

    def test_a_five_to_one_split_is_detected(self, cfg):
        events = detect(series([1000.0, 1000.0, 201.7, 202.0]), cfg)
        assert events[0].factor == pytest.approx(0.2)

    def test_a_normal_series_produces_nothing(self, cfg):
        assert detect(series([100.0, 101.0, 99.5, 102.0, 98.0]), cfg) == []

    def test_a_large_but_ordinary_move_is_not_flagged(self, cfg):
        """A 15% fall is a bad day, not a corporate action."""
        assert detect(series([100.0, 85.0, 84.0]), cfg) == []


class TestTheMatcherIsNotPermissive:
    """The bug: a matcher with too many candidates never refuses anything.

    An earlier version allowed any p/q up to q=20, which placed a candidate
    every 1-2% across the range. With any usable tolerance every observed ratio
    matched something, so demergers were silently laundered into splits.
    """

    def test_the_candidate_set_stayed_small(self):
        assert len(CLEAN_RATIOS) < 80

    def test_an_arbitrary_ratio_matches_nothing(self, cfg):
        """0.225 sits in the widest gap in the candidate set - 12.5% from 1/5,
        10% from 1/4, so nothing matches within the 6% tolerance."""
        events = detect(series([100.0, 100.0, 22.5, 22.7]), cfg)
        assert events and not events[0].adjustable
        assert events[0].kind == "unmatched"

    def test_an_upward_jump_is_never_treated_as_a_split(self, cfg):
        events = detect(series([100.0, 100.0, 230.0, 232.0]), cfg)
        assert not events[0].adjustable


class TestDataGapsAreNotCorporateActions:
    """The second bug: a ratio measured across a hole in the series.

    CGPOWER has no bars between 2021-09-15 and 2022-01-04 because the EQ-series
    filter drops a stock while it sits in the BE segment under surveillance.
    Comparing the prices either side produced a phantom 2.3x "split".
    """

    def test_a_long_gap_is_classified_as_a_gap(self, cfg):
        s = pd.Series(
            [89.5, 89.0, 204.6, 202.75],
            index=pd.to_datetime(["2021-09-14", "2021-09-15", "2022-01-04", "2022-01-05"]),
        )
        events = detect(s, cfg)
        assert events[0].kind == "data_gap"
        assert events[0].gap_days > 100

    def test_a_gap_is_not_adjustable(self, cfg):
        s = pd.Series(
            [100.0, 100.0, 250.0],
            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-06-01"]),
        )
        assert not detect(s, cfg)[0].adjustable

    def test_a_normal_weekend_is_not_a_gap(self, cfg):
        """Friday to Monday is three calendar days and must stay eligible."""
        s = pd.Series(
            [100.0, 100.0, 50.1],
            index=pd.to_datetime(["2024-01-04", "2024-01-05", "2024-01-08"]),
        )
        assert detect(s, cfg)[0].kind == "split"


class TestAdjustment:
    def test_prices_before_the_event_are_scaled(self, cfg):
        df = frame([2000.0, 2000.0, 1000.0, 1010.0])
        events = detect(df["close"], cfg)
        out = adjust(df, events)
        assert out["close"].iloc[0] == pytest.approx(1000.0)
        assert out["close"].iloc[2] == pytest.approx(1000.0)

    def test_prices_after_the_event_are_untouched(self, cfg):
        df = frame([2000.0, 2000.0, 1000.0, 1010.0])
        out = adjust(df, detect(df["close"], cfg))
        assert out["close"].iloc[3] == pytest.approx(1010.0)

    def test_volume_is_scaled_the_other_way(self, cfg):
        """Rupee turnover must stay comparable across the split."""
        df = frame([2000.0, 2000.0, 1000.0, 1010.0])
        out = adjust(df, detect(df["close"], cfg))
        assert out["volume"].iloc[0] == pytest.approx(2_000_000)

    def test_the_series_is_continuous_afterwards(self, cfg):
        df = frame([2000.0, 2000.0, 1000.0, 1010.0])
        out = adjust(df, detect(df["close"], cfg))
        ratio = out["close"].iloc[2] / out["close"].iloc[1]
        assert 0.9 < ratio < 1.1

    def test_two_splits_compound(self, cfg):
        """Bars before the earlier split must carry both factors."""
        df = frame([4000.0, 4000.0, 2000.0, 2000.0, 1000.0, 1010.0])
        out = adjust(df, detect(df["close"], cfg))
        assert out["close"].iloc[0] == pytest.approx(1000.0)

    def test_an_unadjustable_event_changes_nothing(self, cfg):
        df = frame([100.0, 100.0, 22.5, 22.7])
        out = adjust(df, detect(df["close"], cfg))
        pd.testing.assert_frame_equal(out, df)

    def test_int_volume_survives_a_fractional_factor(self, cfg):
        """Bhavcopy volume is int64; scaling it by 0.5 must not raise."""
        df = frame([2000.0, 2000.0, 1000.0, 1010.0])
        df["volume"] = df["volume"].astype("int64")
        out = adjust(df, detect(df["close"], cfg))
        assert out["volume"].iloc[0] == pytest.approx(2_000_000)

    def test_the_input_frame_is_not_mutated(self, cfg):
        df = frame([2000.0, 2000.0, 1000.0, 1010.0])
        before = df.copy()
        adjust(df, detect(df["close"], cfg))
        pd.testing.assert_frame_equal(df, before)


class TestSourceIntegration:
    def test_reliance_is_continuous_across_the_bonus(self, cfg):
        from datetime import date
        from src.data.nse_source import NsePriceSource, load_cache

        src = NsePriceSource(cfg, frame=load_cache())
        df = src.ohlcv(["RELIANCE"], date(2024, 10, 20), date(2024, 11, 5)).droplevel("symbol")
        ratios = (df["close"] / df["close"].shift(1)).dropna()
        assert ratios.min() > 0.9

    def test_a_gapped_symbol_is_refused_with_a_reason(self, cfg):
        from datetime import date
        from src.data.nse_source import NsePriceSource, load_cache

        src = NsePriceSource(cfg, frame=load_cache())
        assert src.ohlcv(["CGPOWER"], date(2020, 1, 1), date(2026, 8, 21)).empty
        assert "DATA GAP" in src.reports["CGPOWER"].reasons[0]

    def test_summarise_is_readable(self, cfg):
        events = detect(series([2000.0, 2000.0, 1000.0]), cfg)
        assert "split" in summarise(events)
