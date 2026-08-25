"""Regenerate the CSV fixtures.

The fixtures are committed so tests do not depend on running this, but they are
generated rather than hand-typed so each one's verdict is reproducible and the
intent is readable. Run from the project root:

    python tests/fixtures/_generate.py

Each fixture is built to fail exactly one gate of the long screen (or none), so
a screen test can assert both that the right gate fired and that no other did.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

BARS = 320
OUT = Path(__file__).parent


def build(drift: float, wobble: float, pullback_bars: int, pullback_pct: float,
          seed_price: float = 100.0) -> pd.DataFrame:
    """A trend with regular swings, optionally ending in a pullback."""
    closes = []
    for i in range(BARS):
        base = seed_price + drift * i
        closes.append(base + wobble * math.sin(i / 9.0))

    for j in range(pullback_bars):
        k = BARS - pullback_bars + j
        depth = pullback_pct * (j + 1) / pullback_bars
        closes[k] = closes[BARS - pullback_bars - 1] * (1.0 - depth)

    rows = []
    for i, c in enumerate(closes):
        span = max(abs(c) * 0.012, 0.5)
        rows.append(
            {
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=i),
                "open": round(c - span * 0.2, 2),
                "high": round(c + span, 2),
                "low": round(c - span, 2),
                "close": round(c, 2),
                "volume": 100_000 + (i % 7) * 3_000,
            }
        )
    return pd.DataFrame(rows)


def write(name: str, df: pd.DataFrame) -> None:
    df.to_csv(OUT / f"{name}.csv", index=False)
    print(f"wrote {name}.csv  {len(df)} bars  last close {df['close'].iloc[-1]}")


def main() -> None:
    # PASSING: strong uptrend, shallow terminal pullback -> RSI cools to ~39,
    # mid-band rather than near the 30/60 edges so the fixture is not brittle,
    # and price stays above the 50 SMA.
    write("PASSING", build(drift=0.45, wobble=6.0, pullback_bars=6, pullback_pct=0.015))

    # RSIHOT: same trend, no pullback -> RSI stays above the 60 ceiling.
    write("RSIHOT", build(drift=0.45, wobble=6.0, pullback_bars=0, pullback_pct=0.0))

    # DOWNTREND: falling, so price is under the 50 SMA and structure is not HH/HL.
    write("DOWNTREND", build(drift=-0.35, wobble=6.0, pullback_bars=0, pullback_pct=0.0,
                             seed_price=250.0))

    # STALEBARS: the PASSING series with carried-forward non-traded bars spliced
    # in, above the 5% max_stale_bar_pct limit -> the SYMBOL is excluded.
    stale = build(drift=0.45, wobble=6.0, pullback_bars=6, pullback_pct=0.015)
    for i in range(0, BARS, 12):          # ~8% of bars
        c = stale.at[i, "close"]
        stale.loc[i, ["open", "high", "low", "close", "volume"]] = [c, c, c, c, 0]
    write("STALEBARS", stale)


if __name__ == "__main__":
    main()
