"""Fundamental scoring. A gate for the long screen.

Long-only (SPEC.md section 4), so there is no inverted short-side variant here.

STATUS: this module is implemented but CANNOT RUN. Every threshold in
fundamental.long_gate is null, and there is no fundamental data source - see
DATA_AUDIT.md section 4, where FMP, Alpha Vantage and the NSE archives were all
tested and all came back negative. applicable_thresholds() therefore raises
UnresolvedConfig on the first null it needs.

That is deliberate and it is the point. This family carries 0.30 of the
composite weight and has never contributed to a signal or a backtest. The code
exists so that when a source lands the only new work is an adapter behind the
FundamentalSource protocol in data/base.py - the same shape that let
NsePriceSource drop in behind CsvPriceSource without touching strategy code.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..config import UnresolvedConfig, require

# Direction matters: some thresholds are floors, some are ceilings.
FLOORS = {
    "min_roce", "min_roe", "min_ocf_to_pat", "revenue_growth_3y_min",
    "min_roa", "min_net_interest_margin", "min_capital_adequacy_pct",
}
CEILINGS = {
    "max_debt_to_equity", "max_promoter_pledge_pct",
    "max_gross_npa_pct",
}

# threshold key -> the metric name expected on the ratios frame
METRIC_OF = {
    "min_roce": "roce",
    "min_roe": "roe",
    "max_debt_to_equity": "debt_to_equity",
    "min_ocf_to_pat": "ocf_to_pat",
    "max_promoter_pledge_pct": "promoter_pledge_pct",
    "revenue_growth_3y_min": "revenue_growth_3y",
    "min_roa": "roa",
    "min_net_interest_margin": "net_interest_margin",
    "max_gross_npa_pct": "gross_npa_pct",
    "min_capital_adequacy_pct": "capital_adequacy_pct",
}


@dataclass
class FundamentalResult:
    """Never a single opaque number - the breakdown is the point.

    A low rank has to be interrogable: the report shows which component failed
    and by how much, so a threshold can be argued with rather than trusted.
    """

    symbol: str
    sector: str
    score: float                                    # 0..100
    components: dict[str, float] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    metrics_applied: list[str] = field(default_factory=list)
    metrics_excluded: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def applicable_thresholds(sector: str, cfg: dict) -> dict[str, float]:
    """Resolve the threshold set that actually applies to `sector`.

    Not "the same metrics with different numbers". For a lender the generic set
    is wrong: debt-to-equity is meaningless when leverage IS the business model,
    ROCE is not the right capital metric, and OCF-to-PAT swings with the loan
    book rather than measuring earnings quality. So an override removes generic
    metrics and adds sector-specific ones - see the comment in strategy.yaml.

    Raises UnresolvedConfig on the first null. That is the correct behaviour
    while the thresholds are uncalibrated: a gate that silently skips a null is
    a gate that passes every stock.
    """
    generic = dict(cfg["fundamental"]["long_gate"])
    override = (cfg["fundamental"].get("sector_overrides") or {}).get(sector)

    excluded: list[str] = []
    if override:
        excluded = list(override.get("exclude", []))
        for key in excluded:
            generic.pop(key, None)
        generic.update(override.get("thresholds", {}))

    resolved = {}
    for key in generic:
        path = _config_path(key, sector, cfg)
        resolved[key] = require(cfg, path)
    return resolved


def _config_path(key: str, sector: str, cfg: dict) -> str:
    override = (cfg["fundamental"].get("sector_overrides") or {}).get(sector) or {}
    if key in (override.get("thresholds") or {}):
        return f"fundamental.sector_overrides.{sector}.thresholds.{key}"
    return f"fundamental.long_gate.{key}"


def score(
    symbol: str, sector: str, ratios: pd.Series, cfg: dict
) -> FundamentalResult:
    """Return a 0..100 score with the component breakdown visible.

    Components: growth consistency (3Y + TTM), ROE/ROCE, D/E and interest
    coverage, OCF-to-PAT (earnings quality), promoter holding trend and pledge,
    PE vs own 5Y median and vs sector median.

    Never a single opaque number - the report shows the breakdown so a low rank
    can be interrogated.

    A metric the thresholds ask for but the data does not carry is a FAILURE,
    not a pass. Missing fundamental data on a stock being gated on fundamentals
    is a reason to refuse it, not to wave it through.
    """
    thresholds = applicable_thresholds(sector, cfg)
    override = (cfg["fundamental"].get("sector_overrides") or {}).get(sector) or {}

    components: dict[str, float] = {}
    failures: list[str] = []

    for key, limit in thresholds.items():
        metric = METRIC_OF.get(key, key)

        # Direction is validated FIRST, before the data check. An undeclared
        # direction is a config error and must surface whether or not the
        # symbol happens to carry that metric - otherwise the mistake hides
        # until the day a stock arrives with the data, which is the worst
        # possible time to discover it.
        if key not in FLOORS and key not in CEILINGS:
            raise ValueError(
                f"threshold {key!r} is in neither FLOORS nor CEILINGS - its "
                f"direction is undefined, so it cannot be scored"
            )

        if metric not in ratios.index or pd.isna(ratios.get(metric)):
            failures.append(f"{metric}: not available")
            components[metric] = 0.0
            continue

        value = float(ratios[metric])
        if key in FLOORS:
            ok = value >= limit
            headroom = (value - limit) / abs(limit) if limit else 0.0
        else:
            ok = value <= limit
            headroom = (limit - value) / abs(limit) if limit else 0.0

        components[metric] = max(0.0, min(1.0, 0.5 + headroom / 2.0))
        if not ok:
            failures.append(f"{metric}: {value:.2f} vs {limit} ({'min' if key in FLOORS else 'max'})")

    total = 100.0 * sum(components.values()) / len(components) if components else 0.0
    return FundamentalResult(
        symbol=symbol,
        sector=sector,
        score=total,
        components=components,
        failures=failures,
        metrics_applied=sorted(METRIC_OF.get(k, k) for k in thresholds),
        metrics_excluded=sorted(override.get("exclude", [])),
    )


def gate(symbol: str, sector: str, ratios: pd.Series | None, cfg: dict) -> list[str]:
    """Blocking reasons for the long screen. Empty means the stock passes.

    `ratios=None` means no data for this symbol, which blocks - it does not pass.
    """
    if ratios is None:
        return ["fundamental: no data for this symbol"]
    try:
        return score(symbol, sector, ratios, cfg).failures
    except UnresolvedConfig as exc:
        return [f"fundamental: {exc}"]
