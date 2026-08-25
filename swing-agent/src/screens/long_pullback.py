"""Long setup: momentum pullback in an established uptrend.

The only screen in this system. Shorts were dropped by decision - see SPEC.md
section 4. Do not add an inverted copy of this file.
"""
from __future__ import annotations

import pandas as pd

from ..indicators.momentum import histogram_contracting, macd, rsi, stochastic
from ..indicators.pivots import confirmed_as_of, cpr, swing_points
from ..indicators.trend import is_uptrend_structure, relative_strength, sma
from ..indicators.volume import anchored_vwap, volume_dryup, volume_expansion
from .result import SetupResult


def evaluate(df: pd.DataFrame, symbol: str, cfg: dict, ctx: dict) -> SetupResult:
    """Apply gates, then score confirmations.

    Gates (all must hold, per config): close above the 50 SMA, 50 above 200,
    higher-high / higher-low structure, RSI(14) inside its band.

    Confirmations are SCORED, NEVER GATING: stochastic turning up from oversold,
    MACD histogram contracting, volume dry-up then expansion, price above
    anchored VWAP from the last swing low, weekly CPR position, relative
    strength. A setup that fails every confirmation still passes if the gates
    hold; it just ranks badly. Promoting any of these to a gate changes the
    strategy, not just the code.

    EVERY GATE IS EVALUATED - no short-circuiting. SPEC section 8 wants
    near-misses reported with the specific failing condition, and a screen that
    returns after the first failure can only ever name one. The cost is a few
    wasted indicator computations on obvious rejects; the benefit is that the
    daily report can say "failed on RSI and structure" rather than "failed".

    `ctx` carries cross-symbol context the screen cannot compute alone -
    currently just the benchmark close series for relative strength.
    """
    lp = cfg["long_pullback"]
    result = SetupResult(symbol=symbol, passed=False)

    if len(df) < lp["trend"]["sma_fast_above_slow"][1]:
        result.gate_failures.append(
            f"insufficient history: {len(df)} bars, need "
            f"{lp['trend']['sma_fast_above_slow'][1]}"
        )
        return result

    close = df["close"]
    last = close.iloc[-1]

    # --- gates ---------------------------------------------------------
    sma_gate = lp["trend"]["price_above_sma"]
    sma_value = sma(close, sma_gate).iloc[-1]
    if not last > sma_value:
        result.gate_failures.append(
            f"price_above_sma: {last:.2f} not above {sma_gate}SMA {sma_value:.2f}"
        )

    fast, slow = lp["trend"]["sma_fast_above_slow"]
    fast_value, slow_value = sma(close, fast).iloc[-1], sma(close, slow).iloc[-1]
    if not fast_value > slow_value:
        result.gate_failures.append(
            f"sma_fast_above_slow: {fast}SMA {fast_value:.2f} not above "
            f"{slow}SMA {slow_value:.2f}"
        )

    if lp["trend"]["require_higher_high_low"] and not is_uptrend_structure(
        df, lp["trend"]["pivot_lookback"], lp["trend"]["min_swing_points"]
    ):
        result.gate_failures.append(
            f"structure: no {lp['trend']['min_swing_points']} ascending "
            f"high/low pairs on confirmed pivots"
        )

    rsi_value = rsi(close, lp["momentum"]["rsi_period"]).iloc[-1]
    lo, hi = lp["momentum"]["rsi_min"], lp["momentum"]["rsi_max"]
    if pd.isna(rsi_value) or not lo <= rsi_value <= hi:
        result.gate_failures.append(f"rsi: {rsi_value:.1f} outside [{lo}, {hi}]")

    # --- confirmations (scored, never gating) --------------------------
    result.confirmations = _confirmations(df, cfg, ctx)

    result.passed = not result.gate_failures
    if result.passed:
        result.entry = float(last)
        hits = [k for k, v in result.confirmations.items() if v > 0.5]
        result.reason = (
            f"pullback in uptrend, RSI {rsi_value:.0f}, "
            f"{len(hits)}/{len(result.confirmations)} confirmations: "
            f"{', '.join(hits) if hits else 'none'}"
        )
    else:
        result.reason = f"failed {len(result.gate_failures)} gate(s)"
    return result


def _confirmations(df: pd.DataFrame, cfg: dict, ctx: dict) -> dict[str, float]:
    """Each confirmation scores 0.0 or 1.0. Absent inputs score 0.0.

    Scores are absolute, not relative to today's candidate pool - see the
    normalisation note in scoring/composite.py.
    """
    lp = cfg["long_pullback"]
    conf = lp["confirmation"]
    close = df["close"]
    out: dict[str, float] = {}

    st = conf["stochastic"]
    stoch = stochastic(df, k=st["k"], d=st["d"], smooth=st["smooth"])
    k_now, k_prev = stoch["k"].iloc[-1], stoch["k"].iloc[-2] if len(stoch) > 1 else float("nan")
    out["stochastic_turning_up"] = float(
        pd.notna(k_now) and pd.notna(k_prev) and k_prev < st["oversold"] and k_now > k_prev
    )

    m = conf["macd"]
    hist = macd(close, m["fast"], m["slow"], m["signal"])["histogram"]
    out["macd_contracting"] = float(histogram_contracting(hist))

    out["volume_dryup"] = float(volume_dryup(df, conf["volume_dryup_ratio"]))
    out["volume_expansion"] = float(volume_expansion(df, conf["volume_expansion_ratio"]))

    out["above_anchored_vwap"] = float(_above_anchored_vwap(df, lp))
    out["above_weekly_cpr"] = float(_above_cpr(df, conf["cpr_timeframe"]))

    benchmark = ctx.get("benchmark")
    if benchmark is not None:
        # Fraction of horizons outperforming, not all-or-nothing. A pullback in
        # an uptrend genuinely reads as weak on 1M and strong on 3M, and that
        # mixed picture is information - collapsing it to False would score the
        # setup identically to a stock lagging on both, which is the opposite
        # kind of candidate.
        periods = conf["relative_strength_periods"]
        beats = [relative_strength(close, benchmark, p) > 0 for p in periods]
        out["relative_strength"] = sum(beats) / len(beats) if beats else 0.0
    else:
        out["relative_strength"] = 0.0

    return out


def _above_anchored_vwap(df: pd.DataFrame, lp: dict) -> bool:
    pivots = confirmed_as_of(swing_points(df, lp["trend"]["pivot_lookback"]), len(df) - 1)
    lows = pivots[pivots["kind"] == "low"]
    if lows.empty:
        return False
    vwap = anchored_vwap(df, int(lows["bar"].iloc[-1]))
    return bool(pd.notna(vwap.iloc[-1]) and df["close"].iloc[-1] > vwap.iloc[-1])


def _above_cpr(df: pd.DataFrame, timeframe: str) -> bool:
    levels = cpr(df, timeframe)
    if levels.empty:
        return False
    return bool(df["close"].iloc[-1] > levels["pivot"].iloc[-1])
