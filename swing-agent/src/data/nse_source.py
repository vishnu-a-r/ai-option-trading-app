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
import sys
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

    frames, stale = [], []
    for path in sorted(BHAVCOPY.glob("*.csv.gz")):
        stamp = datetime.strptime(path.stem.replace(".csv", ""), "%d%m%Y").date()
        if start and stamp < start:
            continue
        if end and stamp > end:
            continue
        day = _read_bhavcopy(path)
        # Defence in depth against the stale-file trap described in
        # scripts/fetch_bhavcopy.py: NSE answers some non-trading stamps with
        # the PREVIOUS trading day's file, header intact. The fetcher rejects
        # those now, but a cache populated before that fix still holds them and
        # nothing downstream would notice two copies of one day.
        if day.empty or day["date"].iloc[0].date() != stamp:
            stale.append(path.name)
            continue
        frames.append(day)

    if stale:
        print(
            f"warning: skipped {len(stale)} cached files whose DATE1 does not match "
            f"their filename (stale NSE responses); delete and re-fetch them",
            file=sys.stderr,
        )

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


# --- Futures -----------------------------------------------------------------

FO_CACHE = CACHE / "fo"

FO_KEEP = {
    "TckrSymb": "symbol",
    "XpryDt": "expiry",
    "ClsPric": "close",
    "OpnIntrst": "open_interest",
    "ChngInOpnIntrst": "oi_change",
    "TtlTradgVol": "contracts",
    "NewBrdLotQty": "lot_size",
}


def _read_fo(path: Path) -> pd.DataFrame:
    """One day's derivatives bhavcopy, stock futures (STF) only.

    STF is the stock-futures instrument type. The same file also carries STO
    (stock options), IDF and IDO (index futures/options) - roughly 55,000 rows
    against 620 stock-futures rows, so filtering first matters.
    """
    import zipfile

    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as fh:
            df = pd.read_csv(fh)
    df.columns = [c.strip() for c in df.columns]

    df = df[df["FinInstrmTp"] == "STF"].copy()
    df["date"] = pd.to_datetime(df["TradDt"])
    out = df[["date", *FO_KEEP]].rename(columns=FO_KEEP)
    out["expiry"] = pd.to_datetime(out["expiry"])
    return out


def load_fo_cache() -> pd.DataFrame:
    """Every cached F&O day. Indexed (symbol, date), near-month contract only."""
    if not FO_CACHE.is_dir():
        raise FileNotFoundError(
            f"no F&O cache at {FO_CACHE}. Run: python scripts/fetch_fo_bhavcopy.py"
        )

    frames = [_read_fo(p) for p in sorted(FO_CACHE.glob("*.csv.zip"))]
    if not frames:
        raise FileNotFoundError(f"no cached F&O days at {FO_CACHE}")

    out = pd.concat(frames, ignore_index=True)
    # A symbol has up to three live expiries on any day. The near month is the
    # one that carries the liquidity and the signal; far months are thin and
    # their OI moves for rollover reasons rather than directional ones.
    near = out.sort_values("expiry").groupby(["symbol", "date"], as_index=False).first()
    return near.set_index(["symbol", "date"]).sort_index()


class NseFuturesSource:
    """FuturesSource over the cached derivatives bhavcopy.

    Serves the futures family of the composite score: OI buildup, basis, and
    the contract spec. Rollover needs two consecutive expiries and is left
    unimplemented rather than approximated - see rollover().
    """

    def __init__(self, cfg: dict, frame: pd.DataFrame | None = None):
        self.cfg = cfg
        self._fo = load_fo_cache() if frame is None else frame

    def symbols(self) -> list[str]:
        """Underlyings with stock futures - about 208 of the Nifty 500."""
        return sorted(set(self._fo.index.get_level_values("symbol")))

    def open_interest(
        self, symbols: Iterable[str], start: date, end: date
    ) -> pd.DataFrame:
        return self._slice(symbols, start, end, ["open_interest", "oi_change"])

    def basis(self, symbols: Iterable[str], as_of: date, spot: pd.Series) -> pd.DataFrame:
        """Futures premium/discount to spot, absolute and as a percentage.

        `spot` is the cash close per symbol on the same date; it is passed in
        rather than looked up so this source never has to know about the cash
        source.
        """
        rows = []
        for symbol in symbols:
            try:
                fut = self._fo.loc[(symbol, pd.Timestamp(as_of)), "close"]
            except KeyError:
                continue
            if symbol not in spot.index:
                continue
            cash = float(spot[symbol])
            if cash <= 0:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "futures": float(fut),
                    "spot": cash,
                    "basis": float(fut) - cash,
                    "basis_pct": 100.0 * (float(fut) - cash) / cash,
                }
            )
        return pd.DataFrame(rows).set_index("symbol") if rows else pd.DataFrame()

    def contract_spec(self, symbols: Iterable[str], as_of: date) -> pd.DataFrame:
        """Lot size and expiry. Margin is not in the bhavcopy - see below."""
        rows = []
        for symbol in symbols:
            try:
                row = self._fo.loc[(symbol, pd.Timestamp(as_of))]
            except KeyError:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "lot_size": int(row["lot_size"]),
                    "expiry": row["expiry"].date(),
                    "notional_per_lot": float(row["close"]) * int(row["lot_size"]),
                }
            )
        return pd.DataFrame(rows).set_index("symbol") if rows else pd.DataFrame()

    def rollover(self, symbols: Iterable[str], expiry: date) -> pd.DataFrame:
        """NOT IMPLEMENTED.

        Rollover percentage is near-month OI moving into the next expiry, so it
        needs both contracts on the same day. load_fo_cache() keeps only the
        near month, which is the right default for OI and basis and the wrong
        one here. Implementing this means changing what the cache retains, not
        approximating from one series - a rollover number derived from a single
        expiry is not a rollover number.
        """
        raise NotImplementedError(
            "rollover needs near and next expiry on the same day; load_fo_cache() "
            "keeps only the near month. Widen the cache rather than approximating."
        )

    def oi_buildup(self, symbol: str, as_of: date, price_change: float) -> str | None:
        """Classify the OI/price combination.

        Rising price with rising OI is a long buildup; falling price with rising
        OI is a short buildup. Falling OI is unwinding either way. This is the
        futures confirmation SPEC section 7 asks for.
        """
        try:
            row = self._fo.loc[(symbol, pd.Timestamp(as_of))]
        except KeyError:
            return None
        oi_up = float(row["oi_change"]) > 0
        if price_change > 0:
            return "long_buildup" if oi_up else "short_covering"
        if price_change < 0:
            return "short_buildup" if oi_up else "long_unwinding"
        return None

    def _slice(
        self, symbols: Iterable[str], start: date, end: date, columns: list[str]
    ) -> pd.DataFrame:
        wanted = [s for s in symbols if s in self._fo.index.get_level_values("symbol")]
        if not wanted:
            return pd.DataFrame(columns=columns)
        out = self._fo.loc[wanted, columns]
        dates = out.index.get_level_values("date")
        return out[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))].sort_index()
