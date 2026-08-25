"""Dump one symbol's trade log, for comparison against the TradingView run.

    python scripts/single_symbol_trades.py RELIANCE SBIN BAJFINANCE

Portfolio caps are BYPASSED here on purpose. TradingView runs one symbol with
no concurrent-position, sector or deployed-capital limits, so comparing against
the portfolio-constrained engine would show differences that are the caps doing
their job rather than a bug. This isolates the parts the two implementations
should agree on: gates, stop placement, entry timing, exit timing.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import run
from src.config import load
from src.data.nse_source import (
    BENCHMARK, NsePriceSource, benchmark_series, load_cache, load_index_cache,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--start", default="2020-06-01")
    ap.add_argument("--end", default="2026-08-21")
    args = ap.parse_args()

    cfg = load("config/strategy.yaml")
    # One symbol at a time, and the caps lifted so they cannot mask a mismatch.
    cfg["risk"]["max_concurrent_positions"] = 1
    cfg["risk"]["max_sector_risk_pct"] = 100.0
    cfg["risk"]["max_sector_exposure_pct"] = 1000.0
    cfg["risk"]["max_deployed_pct_of_capital"] = 1000.0
    cfg["risk"]["max_aggregate_open_risk_pct"] = 100.0

    source = NsePriceSource(cfg, frame=load_cache())
    index_close = benchmark_series(load_index_cache(), BENCHMARK)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    for symbol in args.symbols:
        prices = source.ohlcv([symbol], start, end)
        if prices.empty:
            print(f"\n{symbol}: no usable data "
                  f"({source.reports.get(symbol, 'not found')})")
            continue

        report = run(start, end, cfg, prices, {symbol: "X"}, index_close)
        print(f"\n{'=' * 78}\n{symbol}  —  {report.trades} trades, "
              f"win {100 * report.win_rate:.1f}%, avg R {report.avg_r:+.3f} net "
              f"({report.avg_r_gross:+.3f} gross)\n{'=' * 78}")
        print(f"{'entry':<12}{'exit':<12}{'in':>9}{'out':>9}{'stop':>9}"
              f"{'qty':>6}{'R':>7}  reason")
        for t in sorted(report.trade_log, key=lambda x: x.entry_date):
            print(
                f"{str(t.entry_date.date()):<12}"
                f"{str(t.exit_date.date()) if t.exit_date else '':<12}"
                f"{t.entry_price:>9.2f}{(t.exit_price or 0):>9.2f}"
                f"{t.stop_price:>9.2f}{t.qty:>6}{t.r_multiple:>+7.2f}  {t.exit_reason}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
