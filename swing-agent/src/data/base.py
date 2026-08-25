"""Data source contracts.

Every source is defined as a Protocol so the concrete implementation can be
swapped after the Section 12 availability audit without touching strategy code.
Implement against these signatures; do not let strategy modules call an API
directly.
"""
from __future__ import annotations

from datetime import date
from typing import Protocol, Iterable
import pandas as pd


class UniverseSource(Protocol):
    def constituents(self, as_of: date) -> list[str]:
        """Current Nifty 500 symbols. Must be point-in-time for backtests."""

    def fno_symbols(self, as_of: date) -> list[str]:
        """Symbols with stock futures - the only shortable swing universe."""

    def surveillance_flags(self, as_of: date) -> dict[str, list[str]]:
        """symbol -> [ASM, GSM, T2T, ...]"""


class PriceSource(Protocol):
    def ohlcv(
        self, symbols: Iterable[str], start: date, end: date, interval: str = "1d"
    ) -> pd.DataFrame:
        """MultiIndex (symbol, date) with open/high/low/close/volume."""

    def delivery_pct(self, symbols: Iterable[str], start: date, end: date) -> pd.DataFrame:
        """Daily delivery percentage. NSE-specific; no equivalent in most vendors."""


class FundamentalSource(Protocol):
    def ratios(self, symbols: Iterable[str], as_of: date) -> pd.DataFrame:
        """ROE, ROCE, D/E, interest coverage, margins, PE and its 5Y median."""

    def statements(self, symbol: str, periods: int = 12) -> pd.DataFrame:
        """Quarterly revenue, PAT, OCF - for trend and earnings-quality checks."""

    def promoter_pledge(self, symbols: Iterable[str], as_of: date) -> pd.DataFrame:
        ...


class InstitutionalSource(Protocol):
    def shareholding_pattern(self, symbols: Iterable[str], quarters: int = 4) -> pd.DataFrame:
        """QoQ promoter / FII / DII / MF holding percentages."""

    def bulk_block_deals(self, start: date, end: date) -> pd.DataFrame:
        ...

    def market_flows(self, start: date, end: date) -> pd.DataFrame:
        """Aggregate FII/DII daily flow. Regime input, not a stock-level signal."""


class FuturesSource(Protocol):
    def open_interest(self, symbols: Iterable[str], start: date, end: date) -> pd.DataFrame:
        ...

    def basis(self, symbols: Iterable[str], as_of: date) -> pd.DataFrame:
        """Futures premium/discount to spot."""

    def rollover(self, symbols: Iterable[str], expiry: date) -> pd.DataFrame:
        ...

    def contract_spec(self, symbols: Iterable[str], as_of: date) -> pd.DataFrame:
        """Lot size and margin - required on every short signal."""
