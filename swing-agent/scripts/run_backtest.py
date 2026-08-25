"""Run the backtest.

    python scripts/run_backtest.py --start 2020-01-01 --end 2026-08-21
    python scripts/run_backtest.py --sector "Financial Services"

Reports win rate, average R, max drawdown, longest losing streak, and the
regime split SPEC section 10 asks for. Read the NOTE lines at the bottom before
the numbers at the top - they say what the numbers do not account for.
"""
from __future__ import annotations

import argparse
import io as _io
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import run
from src.config import load
from src.data.nse_source import (
    BENCHMARK,
    NsePriceSource,
    NseUniverse,
    benchmark_series,
    load_cache,
    load_index_cache,
    sector_shortlist,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-08-21")
    ap.add_argument("--sector", default=None, help="restrict to one sector")
    ap.add_argument("--limit", type=int, default=None, help="cap symbols, for a fast pass")
    args = ap.parse_args()

    cfg = load("config/strategy.yaml")
    ucfg = yaml.safe_load(_io.open("config/universe.yaml", encoding="utf-8"))
    universe = NseUniverse()
    sectors = universe.sectors()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    cash = load_cache()

    if args.sector:
        symbols, _ = sector_shortlist(universe, args.sector, cash, end, ucfg)
    else:
        symbols = universe.constituents()
    if args.limit:
        symbols = symbols[: args.limit]

    print(f"universe        {len(symbols)} symbols"
          f"{' in ' + args.sector if args.sector else ''}")
    print(f"window          {start} -> {end}")
    print("loading prices and screening for quality...", flush=True)

    source = NsePriceSource(cfg, frame=cash)
    prices = source.ohlcv(symbols, start, end)
    usable = sorted(set(prices.index.get_level_values("symbol")))
    print(f"usable symbols  {len(usable)} "
          f"({len(symbols) - len(usable)} excluded by bar quality)")

    index_close = benchmark_series(load_index_cache(), BENCHMARK)
    print(f"benchmark       {BENCHMARK}, {len(index_close)} days\n")
    print("simulating...", flush=True)

    report = run(start, end, cfg, prices, sectors, index_close)
    print()
    print(report.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
