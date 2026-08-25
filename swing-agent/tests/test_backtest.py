"""Backtest engine.

The first class is the important one. It guards the optimisation the whole
engine rests on: indicators are precomputed over the full history and read at
position t rather than recomputed on a truncated frame. That is only valid
because every indicator used is causal, and if someone adds one that is not,
these fail rather than silently producing a backtest that reads the future.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import (
    RANGE_BOUND,
    TRENDING,
    PreparedSymbol,
    Trade,
    _longest_losing_streak,
    _max_drawdown,
    classify_regime,
    run,
)
from src.config import load
from src.indicators.momentum import rsi
from src.indicators.trend import atr, sma


@pytest.fixture
def cfg():
    return load("config/strategy.yaml")


def synth(n=400, seed=0, drift=0.4, wobble=6.0):
    rng = np.random.default_rng(seed)
    base = 100 + drift * np.arange(n) + wobble * np.sin(np.arange(n) / 9.0)
    noise = rng.normal(0, 0.5, n)
    close = base + noise
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": 100_000 + (np.arange(n) % 7) * 3000,
        },
        index=pd.date_range("2022-01-03", periods=n, freq="B"),
    )


class TestCausality:
    """The optimisation guard. See the module and engine docstrings."""

    @pytest.mark.parametrize("t", [260, 320, 399])
    def test_sma_read_at_t_equals_recomputing_on_a_truncated_frame(self, t):
        df = synth()
        assert sma(df["close"], 50).iloc[t] == pytest.approx(
            sma(df.iloc[: t + 1]["close"], 50).iloc[-1]
        )

    @pytest.mark.parametrize("t", [260, 320, 399])
    def test_rsi_read_at_t_equals_recomputing(self, t):
        df = synth()
        assert rsi(df["close"], 14).iloc[t] == pytest.approx(
            rsi(df.iloc[: t + 1]["close"], 14).iloc[-1]
        )

    @pytest.mark.parametrize("t", [260, 320, 399])
    def test_atr_read_at_t_equals_recomputing(self, t):
        df = synth()
        assert atr(df, 14).iloc[t] == pytest.approx(atr(df.iloc[: t + 1], 14).iloc[-1])

    def test_prepared_gates_agree_with_recomputation(self, cfg):
        """The fast path must agree with the slow, honest one."""
        df = synth()
        p = PreparedSymbol("X", df, cfg)
        for t in (300, 340, 380):
            slow = PreparedSymbol("X", df.iloc[: t + 1], cfg)
            assert p.gates_pass(t, cfg) == slow.gates_pass(len(slow.dates) - 1, cfg)

    def test_confirmed_low_never_uses_an_unconfirmed_pivot(self, cfg):
        df = synth()
        p = PreparedSymbol("X", df, cfg)
        lookback = cfg["long_pullback"]["trend"]["pivot_lookback"]
        lows = p.pivots[p.pivots["kind"] == "low"]
        for _, row in lows.head(5).iterrows():
            bar, confirm = int(row["bar"]), int(row["confirmed_at_bar"])
            assert confirm == bar + lookback
            # One bar before confirmation it must not be visible.
            before = p.confirmed_low(confirm - 1)
            assert before is None or before != float(row["price"])


class TestRegime:
    def test_a_straight_line_is_trending(self):
        s = pd.Series(np.arange(100.0), index=pd.date_range("2024-01-01", periods=100))
        assert classify_regime(s).iloc[-1] == TRENDING

    def test_a_sawtooth_going_nowhere_is_range_bound(self):
        s = pd.Series(
            100 + 5 * np.sin(np.arange(100) / 2.0),
            index=pd.date_range("2024-01-01", periods=100),
        )
        assert classify_regime(s).iloc[-1] == RANGE_BOUND

    def test_the_warmup_window_is_unclassified_not_guessed(self):
        s = pd.Series(np.arange(50.0), index=pd.date_range("2024-01-01", periods=50))
        assert classify_regime(s, window=20).iloc[5] == ""

    def test_it_is_causal(self):
        """Bar t must not move when later bars change."""
        s = pd.Series(
            100 + np.arange(100) * 0.5, index=pd.date_range("2024-01-01", periods=100)
        )
        full = classify_regime(s)
        assert classify_regime(s.iloc[:61]).iloc[60] == full.iloc[60]

    def test_a_tiny_window_is_rejected(self):
        with pytest.raises(ValueError, match="window"):
            classify_regime(pd.Series([1.0, 2.0]), window=1)


class TestTradeMaths:
    def trade(self, entry, stop, exit_price, qty=10):
        t = Trade("X", "IT", pd.Timestamp("2024-01-01"), entry, stop, qty)
        t.exit_price, t.exit_date = exit_price, pd.Timestamp("2024-02-01")
        return t

    def test_a_full_stop_out_is_minus_one_r(self):
        assert self.trade(100.0, 95.0, 95.0).r_multiple == pytest.approx(-1.0)

    def test_twice_the_risk_is_plus_two_r(self):
        assert self.trade(100.0, 95.0, 110.0).r_multiple == pytest.approx(2.0)

    def test_pnl_scales_with_quantity(self):
        assert self.trade(100.0, 95.0, 110.0, qty=10).pnl == pytest.approx(100.0)

    def test_an_unexited_trade_is_zero_not_an_error(self):
        assert Trade("X", "IT", pd.Timestamp("2024-01-01"), 100.0, 95.0, 10).r_multiple == 0.0


class TestMetrics:
    def test_max_drawdown_measures_peak_to_trough(self):
        curve = pd.Series([100.0, 120.0, 90.0, 110.0])
        assert _max_drawdown(curve) == pytest.approx(0.25)   # 120 -> 90

    def test_a_rising_curve_has_no_drawdown(self):
        assert _max_drawdown(pd.Series([100.0, 110.0, 120.0])) == pytest.approx(0.0)

    def test_empty_curve_is_zero_not_an_error(self):
        assert _max_drawdown(pd.Series(dtype=float)) == 0.0

    def test_losing_streak_counts_consecutive_losers_in_exit_order(self):
        def t(r_exit, day):
            tr = Trade("X", "IT", pd.Timestamp("2024-01-01"), 100.0, 95.0, 1)
            tr.exit_price, tr.exit_date = r_exit, pd.Timestamp(day)
            return tr
        trades = [t(95.0, "2024-02-01"), t(95.0, "2024-02-02"),
                  t(110.0, "2024-02-03"), t(95.0, "2024-02-04")]
        assert _longest_losing_streak(trades) == 2

    def test_all_winners_means_no_streak(self):
        tr = Trade("X", "IT", pd.Timestamp("2024-01-01"), 100.0, 95.0, 1)
        tr.exit_price, tr.exit_date = 110.0, pd.Timestamp("2024-02-01")
        assert _longest_losing_streak([tr]) == 0


class TestRunHonesty:
    """What the report must always admit."""

    def frame(self, symbols=("AAA", "BBB")):
        parts = []
        for i, s in enumerate(symbols):
            df = synth(seed=i)
            df["symbol"] = s
            parts.append(df.set_index("symbol", append=True).reorder_levels([1, 0]))
        out = pd.concat(parts).sort_index()
        out.index.names = ["symbol", "date"]
        return out

    def index_series(self):
        return pd.Series(
            100 + np.arange(400) * 0.4,
            index=pd.date_range("2022-01-03", periods=400, freq="B"),
        )

    def test_survivorship_is_always_declared(self, cfg):
        report = run(
            date(2022, 1, 3), date(2023, 12, 29), cfg,
            self.frame(), {"AAA": "IT", "BBB": "IT"}, self.index_series(),
        )
        assert report.survivorship_corrected is False
        assert any("SURVIVORSHIP" in n for n in report.notes)

    def test_the_missing_target_rule_is_declared(self, cfg):
        report = run(
            date(2022, 1, 3), date(2023, 12, 29), cfg,
            self.frame(), {"AAA": "IT", "BBB": "IT"}, self.index_series(),
        )
        assert any("NO TARGET" in n for n in report.notes)

    def test_an_empty_window_is_an_error_not_a_silent_zero(self, cfg):
        with pytest.raises(ValueError, match="no trading days"):
            run(
                date(2019, 1, 1), date(2019, 2, 1), cfg,
                self.frame(), {"AAA": "IT", "BBB": "IT"}, self.index_series(),
            )

    def test_it_raises_if_the_sector_taxonomy_is_unset(self, cfg):
        import copy
        unset = copy.deepcopy(cfg)
        unset["risk"]["sector_taxonomy"] = None
        from src.config import UnresolvedConfig
        with pytest.raises(UnresolvedConfig):
            run(
                date(2022, 1, 3), date(2023, 12, 29), unset,
                self.frame(), {"AAA": "IT", "BBB": "IT"}, self.index_series(),
            )

    def test_no_position_exceeds_the_concurrent_cap(self, cfg):
        report = run(
            date(2022, 1, 3), date(2023, 12, 29), cfg,
            self.frame(("AAA", "BBB", "CCC", "DDD")),
            {s: "IT" for s in ("AAA", "BBB", "CCC", "DDD")},
            self.index_series(),
        )
        by_day: dict = {}
        for t in report.trade_log:
            for d in pd.date_range(t.entry_date, t.exit_date or t.entry_date, freq="B"):
                by_day[d] = by_day.get(d, 0) + 1
        if by_day:
            assert max(by_day.values()) <= cfg["risk"]["max_concurrent_positions"]
