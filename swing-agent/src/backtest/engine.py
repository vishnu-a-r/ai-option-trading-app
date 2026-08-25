"""Backtest. Nothing goes live until this reports honest numbers.

Minimum: 5 years, must include 2020 and the 2022 drawdown.

Report: win rate, average R multiple, max drawdown, longest losing streak, and
results split by market regime (trending vs range-bound).

SURVIVORSHIP BIAS: screening the *current* Nifty 500 over history is a
look-ahead error - it silently excludes every stock that fell out of the index.
Use point-in-time constituents if the data allows. If it does not, say so
explicitly in the report rather than quietly overstating returns.

---

HOW THIS AVOIDS LOOKAHEAD, because that is the only thing that matters here.

Indicators are precomputed once per symbol over the full history and then read
at position t, rather than recomputed on df.iloc[:t+1] for every bar. Those are
equivalent ONLY because every indicator used is causal - the value at bar t
depends on bars <= t and nothing later. That equivalence is asserted directly in
tests/test_backtest.py rather than assumed; if someone adds a centred moving
average or a normalisation over the whole series, the test fails and this
optimisation stops being valid.

Pivots are the exception and are handled separately. A swing low at bar i is not
knowable until bar i + lookback, so swing_points() carries confirmed_at_bar and
the simulation filters on it. Filtering on the pivot's own bar would let the
backtest anchor a stop to a low the market had not yet confirmed, which flatters
every entry in the run.

Entries fill at the NEXT bar's open, never at the signal bar's close. A signal
is generated from a completed bar, so acting on it inside that same bar is
lookahead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from ..config import require
from ..indicators.momentum import histogram_contracting, macd, rsi, stochastic
from ..indicators.pivots import swing_points
from ..indicators.trend import atr, sma
from ..indicators.volume import volume_dryup
from ..risk.sizing import Position, portfolio_gates, size_with_reason

TRENDING = "trending"
RANGE_BOUND = "range_bound"


@dataclass
class Trade:
    symbol: str
    sector: str
    entry_date: pd.Timestamp
    entry_price: float
    stop_price: float
    qty: int
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    regime: str = ""

    @property
    def risk_per_share(self) -> float:
        return self.entry_price - self.stop_price

    @property
    def r_multiple(self) -> float:
        """Result in units of the amount risked. The only comparable measure."""
        if self.exit_price is None or self.risk_per_share <= 0:
            return 0.0
        return (self.exit_price - self.entry_price) / self.risk_per_share

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return self.qty * (self.exit_price - self.entry_price)


@dataclass
class BacktestReport:
    trades: int
    win_rate: float
    avg_r: float
    max_drawdown: float
    longest_losing_streak: int
    by_regime: dict[str, dict]
    survivorship_corrected: bool
    notes: list[str]
    equity_curve: pd.Series = field(default_factory=pd.Series)
    trade_log: list[Trade] = field(default_factory=list)
    exit_reasons: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"trades                 {self.trades}",
            f"win rate               {100 * self.win_rate:.1f}%",
            f"average R              {self.avg_r:+.3f}",
            f"max drawdown           {100 * self.max_drawdown:.1f}%",
            f"longest losing streak  {self.longest_losing_streak}",
        ]
        if self.exit_reasons:
            lines.append("exits                  " + ", ".join(
                f"{k}={v}" for k, v in sorted(self.exit_reasons.items())
            ))
        for regime, stats in sorted(self.by_regime.items()):
            lines.append(
                f"  {regime:<14} trades={stats['trades']:<5} "
                f"win={100 * stats['win_rate']:.1f}%  avgR={stats['avg_r']:+.3f}"
            )
        if self.notes:
            lines.append("")
            lines.extend(f"NOTE: {n}" for n in self.notes)
        return "\n".join(lines)


def classify_regime(index_close: pd.Series, window: int = 20, threshold: float = 0.35) -> pd.Series:
    """Trending vs range-bound, on the index.

    Kaufman efficiency ratio: net move over `window` divided by the sum of the
    absolute daily moves across it. A straight line scores 1.0; a series that
    wanders back to where it started scores near 0. Causal by construction -
    bar t uses bars t-window..t and nothing later.

    A pullback system's edge is regime-dependent and a single blended number
    hides that, which is why SPEC section 10 asks for the split.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")

    net = (index_close - index_close.shift(window)).abs()
    path = index_close.diff().abs().rolling(window).sum()
    efficiency = net / path.where(path != 0)
    return pd.Series(
        np.where(efficiency.isna(), "", np.where(efficiency >= threshold, TRENDING, RANGE_BOUND)),
        index=index_close.index,
    )


class PreparedSymbol:
    """One symbol's precomputed, causal indicator series.

    Built once, read per bar. See the lookahead note in the module docstring for
    why that is equivalent to recomputing on a truncated frame, and for the one
    exception (pivots) that is handled by confirmed_at_bar rather than by this.
    """

    def __init__(self, symbol: str, df: pd.DataFrame, cfg: dict):
        lp = cfg["long_pullback"]
        conf = lp["confirmation"]
        close = df["close"]

        self.symbol = symbol
        self.df = df
        self.dates = df.index
        self.open = df["open"].to_numpy(float)
        self.high = df["high"].to_numpy(float)
        self.low = df["low"].to_numpy(float)
        self.close = close.to_numpy(float)

        fast, slow = lp["trend"]["sma_fast_above_slow"]
        self.sma_gate = sma(close, lp["trend"]["price_above_sma"]).to_numpy(float)
        self.sma_fast = sma(close, fast).to_numpy(float)
        self.sma_slow = sma(close, slow).to_numpy(float)
        self.rsi = rsi(close, lp["momentum"]["rsi_period"]).to_numpy(float)
        self.atr = atr(df, cfg["risk"]["atr_period"]).to_numpy(float)

        m = conf["macd"]
        self.hist = macd(close, m["fast"], m["slow"], m["signal"])["histogram"]
        st = conf["stochastic"]
        self.stoch_k = stochastic(df, st["k"], st["d"], st["smooth"])["k"].to_numpy(float)

        self.pivots = swing_points(df, lp["trend"]["pivot_lookback"])
        self._lows = self.pivots[self.pivots["kind"] == "low"]

    def confirmed_low(self, t: int) -> float | None:
        """Last swing low the market had confirmed by bar t. See module docstring."""
        eligible = self._lows[self._lows["confirmed_at_bar"] <= t]
        return None if eligible.empty else float(eligible["price"].iloc[-1])

    def gates_pass(self, t: int, cfg: dict) -> bool:
        lp = cfg["long_pullback"]
        lo, hi = lp["momentum"]["rsi_min"], lp["momentum"]["rsi_max"]
        if np.isnan(self.sma_slow[t]) or np.isnan(self.rsi[t]):
            return False
        if not self.close[t] > self.sma_gate[t]:
            return False
        if not self.sma_fast[t] > self.sma_slow[t]:
            return False
        if not lo <= self.rsi[t] <= hi:
            return False
        return self._structure_ok(t, lp)

    def _structure_ok(self, t: int, lp: dict) -> bool:
        need = lp["trend"]["min_swing_points"]
        seen = self.pivots[self.pivots["confirmed_at_bar"] <= t]
        highs = seen[seen["kind"] == "high"]["price"].tail(need)
        lows = seen[seen["kind"] == "low"]["price"].tail(need)
        if len(highs) < need or len(lows) < need:
            return False
        return bool((highs.diff().dropna() > 0).all() and (lows.diff().dropna() > 0).all())

    def setup_quality(self, t: int, cfg: dict) -> float:
        """0..1 from the confirmations, used only to rank same-day candidates."""
        conf = cfg["long_pullback"]["confirmation"]
        score = 0.0
        if t > 0 and not np.isnan(self.stoch_k[t]) and not np.isnan(self.stoch_k[t - 1]):
            if self.stoch_k[t - 1] < conf["stochastic"]["oversold"] and self.stoch_k[t] > self.stoch_k[t - 1]:
                score += 1.0
        if histogram_contracting(self.hist.iloc[: t + 1]):
            score += 1.0
        if volume_dryup(self.df.iloc[: t + 1], conf["volume_dryup_ratio"]):
            score += 1.0
        return score / 3.0

    def stop_for(self, t: int, cfg: dict) -> float | None:
        """Structural stop as of bar t. None means no trade - never a percentage."""
        low = self.confirmed_low(t)
        if low is None or np.isnan(self.atr[t]):
            return None
        return low - cfg["risk"]["atr_stop_buffer"] * self.atr[t]


def run(
    start: date,
    end: date,
    cfg: dict,
    prices: pd.DataFrame,
    sectors: dict[str, str],
    index_close: pd.Series,
    warmup_bars: int = 250,
) -> BacktestReport:
    """Simulate the long screen with the real portfolio gates.

    `prices` is a (symbol, date) MultiIndex frame, already quality-screened.

    The portfolio caps are enforced, not ignored. A backtest that takes every
    signal measures a strategy nobody could have run: with Rs 2,00,000 and six
    slots, most signals are refused for want of capital, and the ones that fill
    are whichever happened to rank first that day. Reporting the unconstrained
    number would overstate the system by exactly the amount the constraints cost.
    """
    require(cfg, "risk.sector_taxonomy")
    capital = float(cfg["risk"]["capital_inr"])
    time_stop = cfg["risk"]["time_stop_bars"]

    symbols = sorted(set(prices.index.get_level_values("symbol")))
    prepared: dict[str, PreparedSymbol] = {}
    for symbol in symbols:
        df = prices.loc[symbol].sort_index()
        if len(df) < warmup_bars:
            continue
        prepared[symbol] = PreparedSymbol(symbol, df, cfg)

    calendar = sorted({d for p in prepared.values() for d in p.dates})
    calendar = [d for d in calendar if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    if not calendar:
        raise ValueError(f"no trading days between {start} and {end}")

    regimes = classify_regime(index_close)
    position_of: dict[str, int] = {}   # symbol -> index into `prepared[s].dates`
    open_trades: list[Trade] = []
    closed: list[Trade] = []
    pending: list[tuple[str, float, float]] = []   # (symbol, stop, quality)
    equity = capital
    curve: list[tuple[pd.Timestamp, float]] = []
    bars_held: dict[str, int] = {}

    for day in calendar:
        # 1. Exits first. A position that stops out today frees its slot today.
        still_open = []
        for trade in open_trades:
            p = prepared[trade.symbol]
            t = _index_of(p, day)
            if t is None:
                still_open.append(trade)
                continue
            bars_held[trade.symbol] = bars_held.get(trade.symbol, 0) + 1

            exit_price, reason = _check_exit(p, t, trade, bars_held[trade.symbol], time_stop)
            if exit_price is None:
                still_open.append(trade)
                continue

            trade.exit_date, trade.exit_price, trade.exit_reason = day, exit_price, reason
            equity += trade.pnl
            closed.append(trade)
            bars_held.pop(trade.symbol, None)
        open_trades = still_open

        # 2. Fill yesterday's signals at today's open - never the signal bar's close.
        for symbol, stop, _quality in pending:
            p = prepared[symbol]
            t = _index_of(p, day)
            if t is None:
                continue
            entry = p.open[t]
            if entry <= stop:                      # gapped through the stop overnight
                continue
            qty, _ = size_with_reason(entry, stop, capital, cfg)
            if qty <= 0:
                continue
            candidate = Position(symbol, sectors.get(symbol, "UNKNOWN"), qty, entry, stop)
            if portfolio_gates([_as_position(t_, sectors) for t_ in open_trades], candidate, cfg):
                continue
            open_trades.append(
                Trade(
                    symbol=symbol,
                    sector=sectors.get(symbol, "UNKNOWN"),
                    entry_date=day,
                    entry_price=entry,
                    stop_price=stop,
                    qty=qty,
                    regime=_regime_on(regimes, day),
                )
            )
            bars_held[symbol] = 0
        pending = []

        # 3. Screen for tomorrow.
        held = {t_.symbol for t_ in open_trades}
        signals = []
        for symbol, p in prepared.items():
            if symbol in held:
                continue
            t = _index_of(p, day)
            if t is None or t < warmup_bars:
                continue
            if not p.gates_pass(t, cfg):
                continue
            stop = p.stop_for(t, cfg)
            if stop is None or stop >= p.close[t]:
                continue
            signals.append((symbol, stop, p.setup_quality(t, cfg)))

        signals.sort(key=lambda x: -x[2])
        pending = signals[: cfg["scoring"]["top_n_long"]]

        equity_now = equity + sum(
            t_.qty * (_close_on(prepared[t_.symbol], day) - t_.entry_price) for t_ in open_trades
        )
        curve.append((day, equity_now))

    for trade in open_trades:
        trade.exit_reason = "open_at_end"
    return _report(closed, curve, capital, cfg)


def _as_position(trade: Trade, sectors: dict[str, str]) -> Position:
    return Position(trade.symbol, trade.sector, trade.qty, trade.entry_price, trade.stop_price)


def _index_of(p: PreparedSymbol, day: pd.Timestamp) -> int | None:
    pos = p.dates.searchsorted(day)
    if pos >= len(p.dates) or p.dates[pos] != day:
        return None
    return int(pos)


def _close_on(p: PreparedSymbol, day: pd.Timestamp) -> float:
    t = _index_of(p, day)
    return p.close[t] if t is not None else p.close[-1]


def _regime_on(regimes: pd.Series, day: pd.Timestamp) -> str:
    try:
        value = regimes.loc[day]
    except KeyError:
        return ""
    return value if isinstance(value, str) else ""


def _check_exit(
    p: PreparedSymbol, t: int, trade: Trade, held: int, time_stop: int
) -> tuple[float | None, str]:
    """Stop first, then the time stop.

    A gap through the stop fills at the OPEN, not at the stop price. Assuming
    the stop price on a gap day is the single most common way a backtest
    invents money it could not have made.
    """
    if p.open[t] <= trade.stop_price:
        return p.open[t], "stop_gap"
    if p.low[t] <= trade.stop_price:
        return trade.stop_price, "stop"
    if held >= time_stop:
        return p.close[t], "time_stop"
    return None, ""


def _report(closed: list[Trade], curve, capital: float, cfg: dict) -> BacktestReport:
    notes = [
        "SURVIVORSHIP BIAS NOT CORRECTED: the current Nifty 500 list is applied "
        "across history, so every stock that fell out of the index is silently "
        "excluded. No point-in-time constituent source was found. Results are "
        "overstated by an unknown amount.",
    ]
    if cfg["risk"].get("target_r_multiple") is None and cfg["risk"].get("trailing") is None:
        notes.append(
            "NO TARGET OR TRAILING RULE is configured, so positions exit only on "
            "the stop or after time_stop_bars. This measures the setup unmanaged "
            "and gives winners back, so it likely understates a system that would "
            "take profit. Read these as a floor for the setup."
        )

    equity_curve = pd.Series(dict(curve)).sort_index() if curve else pd.Series(dtype=float)
    if not closed:
        return BacktestReport(0, 0.0, 0.0, 0.0, 0, {}, False, notes + ["No trades."], equity_curve)

    r_values = [t.r_multiple for t in closed]
    wins = [r for r in r_values if r > 0]

    exit_reasons: dict[str, int] = {}
    for t in closed:
        exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1

    by_regime = {}
    for regime in (TRENDING, RANGE_BOUND):
        subset = [t for t in closed if t.regime == regime]
        if subset:
            rs = [t.r_multiple for t in subset]
            by_regime[regime] = {
                "trades": len(subset),
                "win_rate": sum(1 for r in rs if r > 0) / len(rs),
                "avg_r": float(np.mean(rs)),
            }

    return BacktestReport(
        trades=len(closed),
        win_rate=len(wins) / len(closed),
        avg_r=float(np.mean(r_values)),
        max_drawdown=_max_drawdown(equity_curve),
        longest_losing_streak=_longest_losing_streak(closed),
        by_regime=by_regime,
        survivorship_corrected=False,
        notes=notes,
        equity_curve=equity_curve,
        trade_log=closed,
        exit_reasons=exit_reasons,
    )


def _max_drawdown(curve: pd.Series) -> float:
    """Largest peak-to-trough fall on the equity curve, as a fraction."""
    if curve.empty:
        return 0.0
    peak = curve.cummax()
    return float((1.0 - curve / peak).max())


def _longest_losing_streak(closed: list[Trade]) -> int:
    """Consecutive losers in exit order - what the run actually felt like."""
    ordered = sorted(closed, key=lambda t: t.exit_date or pd.Timestamp.min)
    longest = run_len = 0
    for trade in ordered:
        run_len = run_len + 1 if trade.r_multiple <= 0 else 0
        longest = max(longest, run_len)
    return longest
