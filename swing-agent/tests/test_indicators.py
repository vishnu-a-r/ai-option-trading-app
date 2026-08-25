"""Indicators.

Two tests here exist to stop a specific future edit rather than to check today's
arithmetic: the Wilder-vs-simple divergence tests, and the lookahead test. Both
are guarding a decision that looks like a detail and is not.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.indicators.momentum import histogram_contracting, macd, rsi, stochastic
from src.indicators.pivots import cpr, support_resistance_levels
from src.indicators.trend import (
    atr,
    ema,
    is_uptrend_structure,
    relative_strength,
    sma,
    true_range,
)
from src.indicators.volume import (
    anchored_vwap,
    delivery_trend,
    volume_dryup,
    volume_expansion,
)


def ohlcv(closes, highs=None, lows=None, volumes=None, start="2024-01-01"):
    n = len(closes)
    highs = highs if highs is not None else [c + 1 for c in closes]
    lows = lows if lows is not None else [c - 1 for c in closes]
    volumes = volumes if volumes is not None else [100_000] * n
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=pd.date_range(start, periods=n, freq="D"),
    )


class TestMovingAverages:
    def test_sma_is_the_mean_of_the_window(self):
        out = sma(pd.Series([1.0, 2, 3, 4, 5]), 3)
        assert out.iloc[2] == 2.0 and out.iloc[4] == 4.0

    def test_sma_has_no_value_before_a_full_window(self):
        assert sma(pd.Series([1.0, 2, 3]), 3).iloc[:2].isna().all()

    def test_ema_reacts_faster_than_sma_to_a_jump(self):
        s = pd.Series([10.0] * 20 + [20.0] * 5)
        assert ema(s, 10).iloc[-1] > sma(s, 10).iloc[-1]

    @pytest.mark.parametrize("fn", [sma, ema])
    def test_non_positive_period_rejected(self, fn):
        with pytest.raises(ValueError, match="period"):
            fn(pd.Series([1.0, 2, 3]), 0)


class TestTrueRangeAndATR:
    def test_true_range_uses_the_gap_not_just_the_bar(self):
        # Close 100, then a bar entirely above it: the gap is the real range.
        df = ohlcv([100.0, 110.0], highs=[101.0, 111.0], lows=[99.0, 109.0])
        assert true_range(df).iloc[1] == pytest.approx(11.0)  # |111 - 100|

    def test_atr_is_wilder_not_a_simple_mean(self):
        """The guard. If someone swaps atr() for .rolling().mean(), this fails."""
        rng = np.random.default_rng(0)
        closes = 100 + np.cumsum(rng.normal(0, 2, 120))
        df = ohlcv(list(closes), highs=list(closes + 2), lows=list(closes - 2))
        wilder = atr(df, 14).iloc[-1]
        simple = true_range(df).rolling(14).mean().iloc[-1]
        assert not np.isclose(wilder, simple, rtol=1e-6)

    def test_atr_is_positive_on_a_normal_series(self):
        df = ohlcv([100.0 + i for i in range(40)])
        assert atr(df, 14).iloc[-1] > 0

    def test_atr_is_empty_when_there_are_too_few_bars(self):
        assert atr(ohlcv([100.0, 101.0, 102.0]), 14).isna().all()

    def test_atr_seeds_at_the_period_bar_not_before(self):
        df = ohlcv([100.0 + i for i in range(40)])
        out = atr(df, 14)
        assert pd.isna(out.iloc[13]) and pd.notna(out.iloc[14])

    def test_atr_survives_a_dropped_bar_gap(self):
        """quality.clean_ohlcv() removes bars; the resulting gap is real range."""
        df = ohlcv([100.0 + i for i in range(40)])
        gapped = df.drop(df.index[20])
        assert atr(gapped, 14).iloc[-1] > 0


class TestRSI:
    def test_rsi_is_wilder_not_a_simple_mean(self):
        """The guard, mirroring the ATR one."""
        rng = np.random.default_rng(1)
        closes = pd.Series(100 + np.cumsum(rng.normal(0, 1.5, 120)))
        wilder = rsi(closes, 14).iloc[-1]

        delta = closes.diff()
        simple = 100 - 100 / (
            1 + delta.clip(lower=0).rolling(14).mean() / (-delta.clip(upper=0)).rolling(14).mean()
        )
        assert not np.isclose(wilder, simple.iloc[-1], rtol=1e-6)

    def test_unbroken_advance_is_one_hundred(self):
        assert rsi(pd.Series([float(i) for i in range(1, 40)]), 14).iloc[-1] == 100.0

    def test_unbroken_decline_is_near_zero(self):
        assert rsi(pd.Series([float(i) for i in range(40, 1, -1)]), 14).iloc[-1] < 1.0

    def test_rsi_stays_inside_zero_and_one_hundred(self):
        rng = np.random.default_rng(2)
        out = rsi(pd.Series(100 + np.cumsum(rng.normal(0, 2, 200))), 14).dropna()
        assert out.between(0, 100).all()

    def test_too_short_a_series_returns_empty(self):
        assert rsi(pd.Series([1.0, 2, 3]), 14).isna().all()


class TestStochastic:
    def test_close_at_the_top_of_the_range_is_one_hundred(self):
        closes = [10.0] * 14 + [20.0]
        df = ohlcv(closes, highs=[20.0] * 15, lows=[10.0] * 15)
        assert stochastic(df, k=14, d=1, smooth=1)["k"].iloc[-1] == pytest.approx(100.0)

    def test_a_flat_window_is_nan_not_fifty(self):
        df = ohlcv([10.0] * 20, highs=[10.0] * 20, lows=[10.0] * 20)
        assert pd.isna(stochastic(df, k=14, d=3, smooth=3)["k"].iloc[-1])

    def test_invalid_parameters_rejected(self):
        with pytest.raises(ValueError):
            stochastic(ohlcv([1.0] * 20), k=0, d=3, smooth=3)


class TestMACD:
    def test_histogram_is_line_minus_signal(self):
        out = macd(pd.Series([100.0 + i for i in range(60)]), 12, 26, 9)
        assert out["histogram"].iloc[-1] == pytest.approx(
            out["macd"].iloc[-1] - out["signal"].iloc[-1]
        )

    def test_fast_must_be_shorter_than_slow(self):
        with pytest.raises(ValueError, match="must be <"):
            macd(pd.Series([1.0] * 60), 26, 12, 9)

    def test_contracting_detects_a_negative_histogram_rising(self):
        assert histogram_contracting(pd.Series([-3.0, -2.0, -1.0]), bars=3)

    def test_a_positive_shrinking_histogram_is_not_contracting(self):
        """Momentum fading is the opposite signal, not the same one."""
        assert not histogram_contracting(pd.Series([3.0, 2.0, 1.0]), bars=3)

    def test_a_deepening_histogram_is_not_contracting(self):
        assert not histogram_contracting(pd.Series([-1.0, -2.0, -3.0]), bars=3)


class TestStructureAndLookahead:
    UPTREND = [1, 1, 3, 1, 1, 5, 1, 1, 7, 1, 1, 1]

    def frame(self, highs):
        return ohlcv([h - 0.5 for h in highs], highs=highs, lows=[h - 2 for h in highs])

    def test_ascending_pivots_are_an_uptrend(self):
        df = self.frame([1.0, 1, 3, 1.5, 1.5, 5, 2, 2, 7, 2.5, 2.5, 2.5])
        assert is_uptrend_structure(df, pivot_lookback=2, min_pairs=2)

    def test_descending_pivots_are_not(self):
        df = self.frame([9.0, 9, 7, 8, 8, 5, 6, 6, 3, 4, 4, 4])
        assert not is_uptrend_structure(df, pivot_lookback=2, min_pairs=2)

    def test_too_few_pivots_is_not_an_uptrend(self):
        assert not is_uptrend_structure(self.frame([1.0, 2, 3, 4, 5]), 2, 2)

    def test_as_of_bar_matches_truncating_the_frame(self):
        """The lookahead guard.

        Standing at bar N must give the same answer as only ever having seen
        bars 0..N. If these disagree, the function is reading the future.
        """
        df = self.frame([1.0, 1, 3, 1.5, 1.5, 5, 2, 2, 7, 2.5, 2.5, 2.5])
        for n in range(6, len(df)):
            assert is_uptrend_structure(df, 2, 2, as_of_bar=n) == is_uptrend_structure(
                df.iloc[: n + 1], 2, 2
            ), f"disagreement at bar {n}"

    def test_min_pairs_must_be_positive(self):
        with pytest.raises(ValueError, match="min_pairs"):
            is_uptrend_structure(self.frame([1.0] * 10), 2, 0)


class TestRelativeStrength:
    def test_outperformance_is_positive(self):
        sym = pd.Series([100.0, 110, 120])
        bench = pd.Series([100.0, 102, 104])
        assert relative_strength(sym, bench, 2) > 0

    def test_underperformance_is_negative(self):
        sym = pd.Series([100.0, 99, 98])
        bench = pd.Series([100.0, 105, 110])
        assert relative_strength(sym, bench, 2) < 0

    def test_too_short_a_series_is_nan(self):
        assert np.isnan(relative_strength(pd.Series([1.0, 2]), pd.Series([1.0, 2]), 21))


class TestVolume:
    def test_dryup_fires_when_the_latest_bar_is_quiet(self):
        df = ohlcv([100.0] * 21, volumes=[100_000] * 20 + [50_000])
        assert volume_dryup(df, ratio=0.7, avg_period=20)

    def test_dryup_does_not_fire_on_an_average_bar(self):
        df = ohlcv([100.0] * 21, volumes=[100_000] * 21)
        assert not volume_dryup(df, ratio=0.7, avg_period=20)

    def test_expansion_fires_on_a_heavy_bar(self):
        df = ohlcv([100.0] * 21, volumes=[100_000] * 20 + [200_000])
        assert volume_expansion(df, ratio=1.5, avg_period=20)

    def test_the_current_bar_is_excluded_from_its_own_benchmark(self):
        """A huge bar must not inflate the average it is measured against."""
        df = ohlcv([100.0] * 21, volumes=[100_000] * 20 + [10_000_000])
        assert volume_expansion(df, ratio=1.5, avg_period=20)

    def test_too_short_a_series_is_false_not_an_error(self):
        assert not volume_dryup(ohlcv([100.0] * 5), 0.7, 20)

    def test_anchored_vwap_is_nan_before_the_anchor(self):
        out = anchored_vwap(ohlcv([100.0] * 10), anchor_idx=5)
        assert out.iloc[:5].isna().all() and out.iloc[5:].notna().all()

    def test_anchored_vwap_sits_inside_the_price_range(self):
        df = ohlcv([100.0, 110, 90, 105, 95])
        out = anchored_vwap(df, anchor_idx=0)
        assert df["low"].min() <= out.iloc[-1] <= df["high"].max()

    def test_anchor_outside_the_frame_is_rejected(self):
        with pytest.raises(ValueError, match="anchor_idx"):
            anchored_vwap(ohlcv([100.0] * 5), anchor_idx=99)

    def test_delivery_trend_above_one_means_rising(self):
        assert delivery_trend(pd.Series([40.0] * 30 + [60.0]), days=30) > 1.0


class TestCPR:
    def test_daily_is_rejected_as_an_intraday_construct(self):
        with pytest.raises(ValueError, match="intraday"):
            cpr(ohlcv([100.0] * 40), timeframe="daily")

    def test_weekly_levels_are_produced(self):
        out = cpr(ohlcv([100.0 + i for i in range(60)]), timeframe="weekly")
        assert not out.empty and {"pivot", "bc", "tc", "width"} <= set(out.columns)

    def test_tc_is_never_below_bc(self):
        out = cpr(ohlcv([100.0 + (i % 7) for i in range(90)]), "weekly")
        assert (out["tc"] >= out["bc"]).all()

    def test_levels_come_from_the_prior_period(self):
        """This week's CPR must be knowable on Monday, so it uses last week."""
        df = ohlcv([100.0 + i for i in range(60)])
        out = cpr(df, "weekly")
        agg = df.resample("W").agg({"high": "max", "low": "min", "close": "last"})
        expected = (agg["high"] + agg["low"] + agg["close"]).iloc[0] / 3.0
        assert out["pivot"].iloc[0] == pytest.approx(expected)


class TestSupportResistance:
    def test_nearby_pivots_collapse_into_one_level(self):
        highs = [1.0, 1, 10.0, 1, 1, 10.05, 1, 1, 10.02, 1, 1, 1]
        df = ohlcv([h - 0.5 for h in highs], highs=highs, lows=[h - 2 for h in highs])
        levels = support_resistance_levels(df, lookback=2, tolerance_pct=1.0)
        near_ten = [x for x in levels if 9.5 < x < 10.5]
        assert len(near_ten) == 1

    def test_distant_pivots_stay_separate(self):
        highs = [1.0, 1, 10.0, 1, 1, 20.0, 1, 1, 30.0, 1, 1, 1]
        df = ohlcv([h - 0.5 for h in highs], highs=highs, lows=[h - 2 for h in highs])
        levels = support_resistance_levels(df, lookback=2, tolerance_pct=1.0)
        assert len([x for x in levels if x > 5]) == 3

    def test_no_pivots_gives_no_levels(self):
        assert support_resistance_levels(ohlcv([100.0 + i for i in range(30)]), 3) == []

    def test_non_positive_tolerance_rejected(self):
        with pytest.raises(ValueError, match="tolerance_pct"):
            support_resistance_levels(ohlcv([100.0] * 20), 3, tolerance_pct=0)
