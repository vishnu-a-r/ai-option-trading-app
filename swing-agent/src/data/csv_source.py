"""CSV-backed PriceSource.

Exists so the strategy layer can be built and tested while the real source is
blocked (DATA_AUDIT.md). It implements the PriceSource Protocol in base.py
exactly, which is the whole point: when NSE access lands, the new source drops
in behind the same interface and nothing in src/screens/ or src/risk/ changes.

This is a test and development source. It is not a data provider - it reads
whatever CSVs you point it at, so the fixtures it reads are only as honest as
whoever wrote them.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from .quality import QualityReport, clean_ohlcv

COLUMNS = ["open", "high", "low", "close", "volume"]


class CsvPriceSource:
    """One `<SYMBOL>.csv` per symbol in `directory`, columns date,o,h,l,c,v.

    Every symbol is run through quality.clean_ohlcv() on read. Symbols whose
    report is not `usable` are EXCLUDED, not returned dirty - see the reasoning
    in quality.py. Their reports stay available on `.reports` so a caller can
    say why a symbol went missing rather than silently dropping it.
    """

    def __init__(self, directory: str | Path, cfg: dict):
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise ValueError(f"not a directory: {self.directory}")
        self.cfg = cfg
        self.reports: dict[str, QualityReport] = {}

    def ohlcv(
        self, symbols: Iterable[str], start: date, end: date, interval: str = "1d"
    ) -> pd.DataFrame:
        """MultiIndex (symbol, date) with open/high/low/close/volume."""
        if interval != "1d":
            raise ValueError(
                f"CsvPriceSource serves daily bars only, got interval={interval!r}"
            )

        frames = []
        for symbol in symbols:
            df = self._read_one(symbol)
            if df is None:
                continue
            window = df.loc[str(start) : str(end)]
            if window.empty:
                continue
            window = window.copy()
            window["symbol"] = symbol
            frames.append(window.set_index("symbol", append=True).reorder_levels([1, 0]))

        if not frames:
            return pd.DataFrame(
                columns=COLUMNS,
                index=pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"]),
            )

        out = pd.concat(frames).sort_index()
        out.index.names = ["symbol", "date"]
        return out

    def delivery_pct(self, symbols: Iterable[str], start: date, end: date) -> pd.DataFrame:
        """Daily delivery percentage. NSE-specific; no equivalent in most vendors.

        Deliberately unavailable rather than empty. Delivery percentage is
        published by NSE and has no vendor substitute (DATA_AUDIT.md section 1),
        so there is no CSV that could honestly stand in for it. Returning an
        empty frame would let the institutional layer score a silent zero.
        """
        raise NotImplementedError(
            "delivery_pct has no source: NSE-published, no vendor equivalent, and "
            "no fixture can stand in for it. See DATA_AUDIT.md section 1."
        )

    def available_symbols(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.csv"))

    def _read_one(self, symbol: str) -> pd.DataFrame | None:
        path = self.directory / f"{symbol}.csv"
        if not path.exists():
            return None

        df = pd.read_csv(path, parse_dates=["date"]).set_index("date")
        missing = [c for c in COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"{path} is missing columns: {missing}")

        clean, report = clean_ohlcv(df[COLUMNS], self.cfg["data_quality"], symbol)
        self.reports[symbol] = report
        return clean if report.usable else None
