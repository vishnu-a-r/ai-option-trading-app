"""NSE archive sources.

These run against a small synthetic bhavcopy rather than the cache, so they pass
on a clean checkout where nobody has run scripts/fetch_bhavcopy.py.
"""
from __future__ import annotations

import gzip
from datetime import date

import pandas as pd
import pytest

from src.config import load
from src.data.nse_source import NsePriceSource, NseUniverse, _read_bhavcopy

HEADER = (
    "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, "
    "LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, "
    "NO_OF_TRADES, DELIV_QTY, DELIV_PER"
)


def row(symbol, day, close, volume, deliv, series="EQ"):
    return (
        f"{symbol}, {series}, {day}, {close-1:.2f}, {close-0.5:.2f}, {close+2:.2f}, "
        f"{close-2:.2f}, {close:.2f}, {close:.2f}, {close:.2f}, {volume}, "
        f"{volume*close/100000:.2f}, 1000, {int(volume*deliv/100)}, {deliv:.2f}"
    )


@pytest.fixture
def cfg():
    return load("config/strategy.yaml")


@pytest.fixture
def bhav_file(tmp_path):
    lines = [
        HEADER,
        row("RELIANCE", "21-Aug-2026", 1316.00, 5_434_871, 62.62),
        row("SBIN", "21-Aug-2026", 800.00, 1_000_000, 57.80),
        row("SOMEBOND", "21-Aug-2026", 100.00, 500, 10.0, series="N1"),
    ]
    p = tmp_path / "21082026.csv.gz"
    p.write_bytes(gzip.compress(("\n".join(lines) + "\n").encode()))
    return p


@pytest.fixture
def frame(bhav_file):
    return _read_bhavcopy(bhav_file).set_index(["symbol", "date"]).sort_index()


class TestBhavcopyParsing:
    def test_padded_column_names_are_handled(self, bhav_file):
        """Bhavcopy headers are space-padded: ' SERIES', not 'SERIES'."""
        df = _read_bhavcopy(bhav_file)
        assert list(df.columns) == [
            "symbol", "date", "open", "high", "low", "close", "volume",
            "delivery_pct", "turnover_cr",
        ]

    def test_only_eq_series_is_kept(self, bhav_file):
        """Bonds and other series share the file and are not equities."""
        assert set(_read_bhavcopy(bhav_file)["symbol"]) == {"RELIANCE", "SBIN"}

    def test_the_date_format_is_parsed(self, bhav_file):
        assert _read_bhavcopy(bhav_file)["date"].iloc[0] == pd.Timestamp("2026-08-21")

    def test_real_reliance_values_survive_the_round_trip(self, bhav_file):
        df = _read_bhavcopy(bhav_file).set_index("symbol")
        assert df.loc["RELIANCE", "volume"] == 5_434_871
        assert df.loc["RELIANCE", "close"] == pytest.approx(1316.00)
        assert df.loc["RELIANCE", "delivery_pct"] == pytest.approx(62.62)

    def test_turnover_is_converted_from_lakhs_to_crore(self, bhav_file):
        df = _read_bhavcopy(bhav_file).set_index("symbol")
        assert df.loc["SBIN", "turnover_cr"] == pytest.approx(8000.0 / 100, rel=1e-3)


class TestNsePriceSource:
    def test_ohlcv_returns_the_protocol_shape(self, cfg, frame):
        src = NsePriceSource(cfg, frame=frame)
        out = src.ohlcv(["RELIANCE"], date(2026, 1, 1), date(2026, 12, 31))
        assert out.index.names == ["symbol", "date"]
        assert list(out.columns) == ["open", "high", "low", "close", "volume"]

    def test_unknown_symbol_is_skipped(self, cfg, frame):
        src = NsePriceSource(cfg, frame=frame)
        assert src.ohlcv(["NOSUCH"], date(2026, 1, 1), date(2026, 12, 31)).empty

    def test_non_daily_interval_is_rejected(self, cfg, frame):
        with pytest.raises(ValueError, match="daily only"):
            NsePriceSource(cfg, frame=frame).ohlcv(
                ["RELIANCE"], date(2026, 1, 1), date(2026, 12, 31), interval="1h"
            )

    def test_delivery_pct_is_served_unlike_the_csv_source(self, cfg, frame):
        """The field DATA_AUDIT.md called unavailable is a bhavcopy column."""
        out = NsePriceSource(cfg, frame=frame).delivery_pct(
            ["RELIANCE"], date(2026, 1, 1), date(2026, 12, 31)
        )
        assert out["delivery_pct"].iloc[0] == pytest.approx(62.62)

    def test_available_symbols_lists_the_cache(self, cfg, frame):
        assert NsePriceSource(cfg, frame=frame).available_symbols() == ["RELIANCE", "SBIN"]

    def test_a_symbol_with_too_few_bars_is_excluded_by_quality(self, cfg, frame):
        """One day cannot satisfy min_bars_required, so the symbol is dropped."""
        src = NsePriceSource(cfg, frame=frame)
        assert src.ohlcv(["RELIANCE"], date(2026, 1, 1), date(2026, 12, 31)).empty
        assert not src.reports["RELIANCE"].usable


class TestStaleFileTrap:
    """NSE answers some non-trading stamps with the PREVIOUS day's file.

    A 200, a valid SYMBOL header, and the wrong data. Fifty of the first 260
    days pulled were silent duplicates. Only DATE1 distinguishes them, and two
    copies of one day double-weight it in every average downstream.
    """

    def test_a_file_whose_date_disagrees_with_its_name_is_detectable(self, tmp_path):
        # File named 22082026 but containing 21-Aug-2026 data - the real case.
        lines = [HEADER, row("RELIANCE", "21-Aug-2026", 1316.00, 5_434_871, 62.62)]
        p = tmp_path / "22082026.csv.gz"
        p.write_bytes(gzip.compress(("\n".join(lines) + "\n").encode()))

        from datetime import datetime

        stamp = datetime.strptime(p.stem.replace(".csv", ""), "%d%m%Y").date()
        inner = _read_bhavcopy(p)["date"].iloc[0].date()
        assert inner != stamp

    def test_the_fetcher_rejects_a_stale_body(self):
        """_dates_match is what stands between the cache and 50 duplicate days."""
        import importlib.util
        from datetime import date as _date

        spec = importlib.util.spec_from_file_location(
            "fetch_bhavcopy", "scripts/fetch_bhavcopy.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        body = (HEADER + "\n" + row("RELIANCE", "21-Aug-2026", 1316.0, 100, 50.0)).encode()
        assert mod._dates_match(body, _date(2026, 8, 21))
        assert not mod._dates_match(body, _date(2026, 8, 22))

    def test_garbage_body_does_not_pass_the_date_check(self):
        import importlib.util
        from datetime import date as _date

        spec = importlib.util.spec_from_file_location(
            "fetch_bhavcopy", "scripts/fetch_bhavcopy.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert not mod._dates_match(b"SYMBOL\nnonsense", _date(2026, 8, 21))


class TestNseUniverse:
    def test_the_real_constituent_list_loads(self):
        u = NseUniverse()
        assert len(u.constituents()) == 500

    def test_sector_labels_are_present(self):
        u = NseUniverse()
        assert u.sector("RELIANCE") is not None

    def test_financial_services_is_the_largest_bucket(self):
        """101 of 500 - a fifth of the index in one sector cap bucket."""
        u = NseUniverse()
        assert len(u.in_sector("Financial Services")) == 101

    def test_hdfc_and_icici_prefixes_can_be_excluded(self):
        u = NseUniverse()
        fin = u.in_sector("Financial Services")
        kept = [s for s in fin if not s.startswith(("HDFC", "ICICI"))]
        assert len(fin) - len(kept) == 7

    def test_missing_symbol_has_no_sector(self):
        assert NseUniverse().sector("NOSUCHSYMBOL") is None

    def test_a_missing_file_is_reported_clearly(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="constituent list"):
            NseUniverse(tmp_path / "nope.csv")


# --- Futures -----------------------------------------------------------------

FO_COLS = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
    "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,"
    "TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4"
)


def fo_row(symbol, expiry, close, oi, oi_chg, lot, tp="STF", trad="2026-08-21"):
    v = {
        "TradDt": trad, "FinInstrmTp": tp, "TckrSymb": symbol, "XpryDt": expiry,
        "ClsPric": close, "OpnIntrst": oi, "ChngInOpnIntrst": oi_chg,
        "TtlTradgVol": 1000, "NewBrdLotQty": lot,
    }
    return ",".join(str(v.get(c, "")) for c in FO_COLS.split(","))


@pytest.fixture
def fo_zip(tmp_path):
    import zipfile
    lines = [
        FO_COLS,
        fo_row("RELIANCE", "2026-08-25", 1310.10, 48_400_000, -25_517_000, 500),
        fo_row("RELIANCE", "2026-10-27", 1324.90, 5_184_500, 475_000, 500),   # far month
        fo_row("SBIN", "2026-08-25", 1042.50, 10_000_000, 250_000, 750),
        fo_row("NIFTY", "2026-08-25", 25000.0, 1_000, 10, 25, tp="IDF"),       # index
    ]
    p = tmp_path / "20260821.csv.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("BhavCopy_NSE_FO_0_0_0_20260821_F_0000.csv", "\n".join(lines) + "\n")
    return p


@pytest.fixture
def fo_frame(fo_zip):
    from src.data.nse_source import _read_fo
    df = _read_fo(fo_zip)
    return (
        df.sort_values("expiry")
        .groupby(["symbol", "date"], as_index=False)
        .first()
        .set_index(["symbol", "date"])
        .sort_index()
    )


class TestFuturesParsing:
    def test_only_stock_futures_are_kept(self, fo_zip):
        """The file is ~55,000 rows of options and index contracts too."""
        from src.data.nse_source import _read_fo
        assert set(_read_fo(fo_zip)["symbol"]) == {"RELIANCE", "SBIN"}

    def test_near_month_wins_over_far_month(self, fo_frame):
        """Far months are thin and their OI moves for rollover reasons."""
        import pandas as pd
        row = fo_frame.loc[("RELIANCE", pd.Timestamp("2026-08-21"))]
        assert row["expiry"] == pd.Timestamp("2026-08-25")
        assert row["open_interest"] == 48_400_000


class TestNseFuturesSource:
    def test_symbols_lists_underlyings(self, cfg, fo_frame):
        from src.data.nse_source import NseFuturesSource
        assert NseFuturesSource(cfg, frame=fo_frame).symbols() == ["RELIANCE", "SBIN"]

    def test_basis_is_futures_minus_spot(self, cfg, fo_frame):
        from src.data.nse_source import NseFuturesSource
        import pandas as pd
        spot = pd.Series({"RELIANCE": 1316.00})
        out = NseFuturesSource(cfg, frame=fo_frame).basis(
            ["RELIANCE"], date(2026, 8, 21), spot
        )
        assert out.loc["RELIANCE", "basis"] == pytest.approx(-5.90)
        assert out.loc["RELIANCE", "basis_pct"] == pytest.approx(-0.448, abs=0.01)

    def test_basis_skips_symbols_with_no_spot(self, cfg, fo_frame):
        from src.data.nse_source import NseFuturesSource
        import pandas as pd
        out = NseFuturesSource(cfg, frame=fo_frame).basis(
            ["RELIANCE"], date(2026, 8, 21), pd.Series(dtype=float)
        )
        assert out.empty

    def test_contract_spec_gives_lot_size_and_notional(self, cfg, fo_frame):
        from src.data.nse_source import NseFuturesSource
        out = NseFuturesSource(cfg, frame=fo_frame).contract_spec(
            ["RELIANCE"], date(2026, 8, 21)
        )
        assert out.loc["RELIANCE", "lot_size"] == 500
        assert out.loc["RELIANCE", "notional_per_lot"] == pytest.approx(655_050.0)

    def test_one_lot_exceeds_the_whole_account(self, cfg, fo_frame):
        """Measured confirmation of the audit's estimate: a single RELIANCE lot
        is Rs 6.55 lakh against Rs 2 lakh capital."""
        from src.data.nse_source import NseFuturesSource
        out = NseFuturesSource(cfg, frame=fo_frame).contract_spec(
            ["RELIANCE"], date(2026, 8, 21)
        )
        assert out.loc["RELIANCE", "notional_per_lot"] > cfg["risk"]["capital_inr"]

    @pytest.mark.parametrize(
        "price_change,oi_change,expected",
        [
            (1.0, 1, "long_buildup"),
            (1.0, -1, "short_covering"),
            (-1.0, 1, "short_buildup"),
            (-1.0, -1, "long_unwinding"),
        ],
    )
    def test_oi_buildup_classification(self, cfg, fo_frame, price_change, oi_change, expected):
        from src.data.nse_source import NseFuturesSource
        f = fo_frame.copy()
        f.loc[("RELIANCE", pd.Timestamp("2026-08-21")), "oi_change"] = oi_change
        assert NseFuturesSource(cfg, frame=f).oi_buildup(
            "RELIANCE", date(2026, 8, 21), price_change
        ) == expected

    def test_unknown_symbol_has_no_buildup(self, cfg, fo_frame):
        from src.data.nse_source import NseFuturesSource
        assert NseFuturesSource(cfg, frame=fo_frame).oi_buildup(
            "NOSUCH", date(2026, 8, 21), 1.0
        ) is None

    def test_rollover_refuses_rather_than_approximating(self, cfg, fo_frame):
        """A rollover number from one expiry is not a rollover number."""
        from src.data.nse_source import NseFuturesSource
        with pytest.raises(NotImplementedError, match="near and next expiry"):
            NseFuturesSource(cfg, frame=fo_frame).rollover(["RELIANCE"], date(2026, 8, 25))
