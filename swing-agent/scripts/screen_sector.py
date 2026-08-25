"""Run the long screen across one sector and print a ranked shortlist.

    python scripts/screen_sector.py --sector "Financial Services" \
        --exclude HDFC ICICI --top 10

WHAT THIS IS NOT. This is the TECHNICAL screen only. There is no fundamental
data source (DATA_AUDIT.md section 4), so fundamental, institutional and futures
families do not contribute. rank() renormalises over what is present and reports
`coverage`, which is printed on every line - a coverage of 0.40 means the score
rests on two of five intended families. Do not read this as a quality ranking.

For Financial Services specifically there is a second reason to be careful: the
generic fundamental thresholds do not apply to banks and NBFCs at all, and
config sector_overrides for BANKING and NBFC are still empty stubs.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load
from src.data.nse_source import (
    NseFuturesSource,
    NsePriceSource,
    NseUniverse,
    load_cache,
    load_fo_cache,
)
from src.indicators.momentum import rsi
from src.risk.sizing import stop_level
from src.scoring.composite import rank
from src.screens.long_pullback import evaluate


@dataclass
class Candidate:
    symbol: str
    components: dict
    entry: float
    stop: float
    reason: str = ""


def technical_score(result) -> float:
    """Gates are pass/fail; the confirmations decide rank among the passes."""
    if not result.confirmations:
        return 0.0
    return sum(result.confirmations.values()) / len(result.confirmations)


# For a long setup: fresh longs entering is the real confirmation; a rally on
# short covering is weaker because it has no new committed buyer behind it;
# fresh shorts against a long setup is the signal arguing with itself.
BUILDUP_SCORE = {
    "long_buildup": 1.00,
    "short_covering": 0.50,
    "long_unwinding": 0.25,
    "short_buildup": 0.00,
}


def futures_score(fut, symbol, as_of, price_change) -> float | None:
    """None means no futures signal today - no contract, or rollover window.

    Returning None rather than a neutral 0.5 is deliberate: rank() renormalises
    the family away, so a cash-only name is compared on what it has instead of
    being marked down for a signal it cannot produce.
    """
    if fut is None:
        return None
    buildup = fut.oi_buildup(symbol, as_of, price_change)
    return None if buildup is None else BUILDUP_SCORE[buildup]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sector", default="Financial Services")
    ap.add_argument("--exclude", nargs="*", default=[], help="symbol prefixes to drop")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--end", default="2026-08-21")
    args = ap.parse_args()

    cfg = load("config/strategy.yaml")
    universe = NseUniverse()
    names = universe.company_names()

    symbols = universe.in_sector(args.sector)
    kept = [s for s in symbols if not s.startswith(tuple(args.exclude))] if args.exclude else symbols
    dropped = sorted(set(symbols) - set(kept))
    print(f"{args.sector}: {len(symbols)} names")
    if dropped:
        print(f"excluded ({', '.join(args.exclude)}): {len(dropped)} -> {', '.join(dropped)}")
    print(f"screening: {len(kept)}\n")

    source = NsePriceSource(cfg, frame=load_cache())
    try:
        futures = NseFuturesSource(cfg, frame=load_fo_cache())
    except FileNotFoundError:
        futures = None
        print("no F&O cache - futures family will be absent from every score\n")
    end = date.fromisoformat(args.end)
    start = date(end.year - 3, 1, 1)

    passes, rejects, unusable = [], [], []
    for symbol in kept:
        df = source.ohlcv([symbol], start, end)
        if df.empty:
            unusable.append((symbol, source.reports.get(symbol)))
            continue
        df = df.droplevel("symbol")
        result = evaluate(df, symbol, cfg, {})
        if result.passed:
            stop = stop_level(df, cfg)
            if stop is None:
                rejects.append((symbol, ["no confirmed swing low to anchor a stop"]))
                continue
            passes.append((symbol, result, df, stop))
        else:
            rejects.append((symbol, result.gate_failures))

    print(f"passed all gates: {len(passes)} | rejected: {len(rejects)} | "
          f"no usable data: {len(unusable)}\n")

    if not passes:
        print("No candidates. Most common failing gate:")
        counts: dict[str, int] = {}
        for _, failures in rejects:
            for f in failures:
                counts[f.split(":")[0]] = counts.get(f.split(":")[0], 0) + 1
        for gate, n in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {gate:<24} {n}")
        return 0

    candidates = []
    for sym, result, df, stop in passes:
        close = df["close"]
        change = float(close.iloc[-1] - close.iloc[-2]) if len(close) > 1 else 0.0
        components = {
            "technical_setup": technical_score(result),
            "relative_strength": 0.0,
        }
        fut_score = futures_score(futures, sym, end, change)
        if fut_score is not None:
            components["futures_confirmation"] = fut_score
        candidates.append(
            Candidate(
                symbol=sym,
                components=components,
                entry=result.entry,
                stop=stop,
                reason=result.reason,
            )
        )
    ranked = rank(candidates, cfg)[: args.top]

    print(f"TOP {len(ranked)} BY TECHNICAL SETUP  (technical only - see module docstring)\n")
    hdr = (f"{'#':<3}{'SYMBOL':<12}{'COMPANY':<30}{'ENTRY':>9}{'STOP':>9}"
           f"{'R%':>7}{'RSI':>5}{'FUT':>6}{'COV':>6}")
    print(hdr)
    print("-" * len(hdr))
    lookup = {s: (r, df) for s, r, df, _ in passes}
    for i, c in enumerate(ranked, 1):
        result, df = lookup[c.symbol]
        r14 = rsi(df["close"], cfg["long_pullback"]["momentum"]["rsi_period"]).iloc[-1]
        risk = c.entry - c.stop
        fut = c.components.get("futures_confirmation")
        print(
            f"{i:<3}{c.symbol:<12}{names.get(c.symbol,'')[:28]:<30}"
            f"{c.entry:>9.2f}{c.stop:>9.2f}{100*risk/c.entry:>6.1f}%"
            f"{r14:>5.0f}{('-' if fut is None else f'{fut:.2f}'):>6}{c.coverage:>6.2f}"
        )
        print(f"   {result.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
