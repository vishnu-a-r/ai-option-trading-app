"""NSE archive data sources.

Reads the free public archives at nsearchives.nseindia.com, which carry
everything DATA_AUDIT.md identified as having no vendor substitute: NSE OHLCV,
delivery percentage, stock-futures open interest, lot size, index membership,
and sector labels.

WHY THE ARCHIVES AND NOT THE JSON API. www.nseindia.com returns 403 to
programmatic requests regardless of network policy - it is bot protection, not
an egress problem. The archive host serves static files and does not do this.
Anything that "needs" the API here is almost certainly available in a bhavcopy
column instead; check before reaching for cookie-juggling against www.

These sources read from the local cache populated by scripts/fetch_bhavcopy.py.
They deliberately do NOT fetch on demand: a screen that silently downloads 250
files the first time it runs is indistinguishable from a hung process, and a
backtest that hits the network per bar is not reproducible.
"""
from __future__ import annotations

import gzip
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from .quality import QualityReport, clean_ohlcv

CACHE = Path(__file__).resolve().parents[2] / "data" / "cache"
BHAVCOPY = CACHE / "bhavcopy"

# Bhavcopy columns are space-padded: " SERIES" not "SERIES".
RENAME = {
    "OPEN_PRICE": "open",
    "HIGH_PRICE": "high",
    "LOW_PRICE": "low",
    "CLOSE_PRICE": "close",
    "TTL_TRD_QNTY": "volume",
}
OHLCV = ["open", "high", "low", "close", "volume"]


def _read_bhavcopy(path: Path) -> pd.DataFrame:
    """One day's file, EQ series only, columns normalised."""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        df = pd.read_csv(fh, skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]

    df = df[df["SERIES"].astype(str).str.strip() == "EQ"].copy()
    df["date"] = pd.to_datetime(df["DATE1"].str.strip(), format="%d-%b-%Y")
    df["symbol"] = df["SYMBOL"].str.strip()

    for src, dst in RENAME.items():
        df[dst] = pd.to_numeric(df[src], errors="coerce")
    df["delivery_pct"] = pd.to_numeric(df["DELIV_PER"], errors="coerce")
    df["turnover_cr"] = pd.to_numeric(df["TURNOVER_LACS"], errors="coerce") / 100.0

    return df[["symbol", "date", *OHLCV, "delivery_pct", "turnover_cr"]]


def load_cache(start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """Every cached bhavcopy day, concatenated. Indexed (symbol, date)."""
    if not BHAVCOPY.is_dir():
        raise FileNotFoundError(
            f"no bhavcopy cache at {BHAVCOPY}. Run: python scripts/fetch_bhavcopy.py"
        )

    frames = []
    for path in sorted(BHAVCOPY.glob("*.csv.gz")):
        stamp = datetime.strptime(path.stem.replace(".csv", ""), "%d%m%Y").date()
        if start and stamp < start:
            continue
        if end and stamp > end:
            continue
        frames.append(_read_bhavcopy(path))

    if not frames:
        raise FileNotFoundError(f"no cached bhavcopy days in range at {BHAVCOPY}")

    out = pd.concat(frames, ignore_index=True)
    return out.set_index(["symbol", "date"]).sort_index()


class NsePriceSource:
    """PriceSource over the cached bhavcopy archive.

    Unlike CsvPriceSource this can serve delivery_pct(), because DELIV_PER is a
    bhavcopy column - the field DATA_AUDIT.md flagged as having no vendor
    equivalent.
    """

    def __init__(self, cfg: dict, frame: pd.DataFrame | None = None):
        self.cfg = cfg
        self._raw = load_cache() if frame is None else frame
        self.reports: dict[str, QualityReport] = {}

    def ohlcv(
        self, symbols: Iterable[str], start: date, end: date, interval: str = "1d"
    ) -> pd.DataFrame:
        if interval != "1d":
            raise ValueError(f"bhavcopy is daily only, got interval={interval!r}")

        frames = []
        for symbol in symbols:
            df = self._one(symbol)
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
                columns=OHLCV,
                index=pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"]),
            )
        out = pd.concat(frames).sort_index()
        out.index.names = ["symbol", "date"]
        return out

    def delivery_pct(self, symbols: Iterable[str], start: date, end: date) -> pd.DataFrame:
        """Daily delivery percentage, straight from DELIV_PER."""
        wanted = [s for s in symbols if s in self._raw.index.get_level_values("symbol")]
        if not wanted:
            return pd.DataFrame(columns=["delivery_pct"])
        out = self._raw.loc[wanted, ["delivery_pct"]]
        mask = (out.index.get_level_values("date") >= pd.Timestamp(start)) & (
            out.index.get_level_values("date") <= pd.Timestamp(end)
        )
        return out[mask].sort_index()

    def available_symbols(self) -> list[str]:
        return sorted(set(self._raw.index.get_level_values("symbol")))

    def _one(self, symbol: str) -> pd.DataFrame | None:
        if symbol not in self._raw.index.get_level_values("symbol"):
            return None
        df = self._raw.loc[symbol, OHLCV].sort_index()
        clean, report = clean_ohlcv(df, self.cfg["data_quality"], symbol)
        self.reports[symbol] = report
        return clean if report.usable else None


class NseUniverse:
    """Nifty 500 membership and sector labels from the constituent CSV.

    NOT point-in-time. This is today's list, and applying it to history is the
    survivorship bias SPEC section 10 warns about - it silently excludes every
    stock that fell out of the index. Fine for screening today; a backtest using
    it overstates results and must say so.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else CACHE / "ind_nifty500list.csv"
        if not self.path.exists():
            raise FileNotFoundError(
                f"constituent list not found at {self.path}. Fetch it from "
                f"nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
            )
        self._df = pd.read_csv(self.path)
        self._df.columns = [c.strip() for c in self._df.columns]
        self._df["Symbol"] = self._df["Symbol"].str.strip()
        self._df["Industry"] = self._df["Industry"].str.strip()

    def constituents(self, as_of: date | None = None) -> list[str]:
        return sorted(self._df["Symbol"].tolist())

    def sector(self, symbol: str) -> str | None:
        row = self._df[self._df["Symbol"] == symbol]
        return None if row.empty else row["Industry"].iloc[0]

    def sectors(self) -> dict[str, str]:
        return dict(zip(self._df["Symbol"], self._df["Industry"]))

    def in_sector(self, industry: str) -> list[str]:
        return sorted(self._df[self._df["Industry"] == industry]["Symbol"].tolist())

    def company_names(self) -> dict[str, str]:
        return dict(zip(self._df["Symbol"], self._df["Company Name"].str.strip()))
