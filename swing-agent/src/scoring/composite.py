"""Composite ranking across the five signal families."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import ConfigError

WEIGHT_TOLERANCE = 1e-9


@dataclass
class ScoredCandidate:
    symbol: str
    composite: float
    components: dict[str, float]
    families_used: list[str]        # which families actually contributed
    entry: float
    stop: float
    targets: list[float] = field(default_factory=list)
    risk_reward: float = 0.0
    qty: int = 0
    reason: str = ""

    # Share of the configured weight this score actually rests on. 1.0 means
    # every family contributed. Anything less means the composite is a
    # confident-looking number derived from part of its intended input, and
    # the report must say so.
    coverage: float = 1.0


def validate_weights(cfg: dict) -> None:
    """Weights must sum to 1.0. Fail loudly at load, not silently at rank time.

    config.load() already calls this path on startup; kept here so a caller
    constructing a config in memory cannot skip it.
    """
    weights = cfg["scoring"]["weights"]
    total = sum(weights.values())
    if abs(total - 1.0) > WEIGHT_TOLERANCE:
        raise ConfigError(f"scoring.weights must sum to 1.0, got {total!r}")


def rank(candidates: list, cfg: dict) -> list[ScoredCandidate]:
    """Weighted blend of technical_setup, fundamental, institutional,
    futures_confirmation, relative_strength.

    THREE DECISIONS WORTH KNOWING ABOUT.

    1. Scores are ABSOLUTE 0..1, not scaled across today's pool. Min-max
       scaling the candidate pool would make the best name on a weak day score
       identically to the best on a strong day, which destroys comparability
       across days and quietly corrupts the backtest meant to validate all of
       this. Each family is responsible for emitting a real 0..1 number, and
       this function asserts the range rather than rescaling into it.

    2. Weights are RENORMALISED over the families actually present. Only about
       180 of the Nifty 500 have stock futures, so scoring a missing family as
       zero would permanently penalise the other ~320 on a 0.10-weight family
       they can never earn - a non-F&O name could not rank alongside an
       otherwise identical F&O one. A candidate is scored on what applies, with
       those weights rescaled to sum to 1.0.

    3. Renormalisation has a sharp edge, so coverage is REPORTED. With no
       fundamental or institutional source today (DATA_AUDIT.md), every
       candidate would otherwise be ranked on technical plus relative strength
       alone - 0.40 of the intended weight, rescaled to 1.00, and printed as a
       confident composite. families_used and coverage make that visible.
       scoring.min_family_coverage, if set, suppresses candidates below it.
    """
    validate_weights(cfg)
    weights = cfg["scoring"]["weights"]
    min_coverage = cfg["scoring"].get("min_family_coverage")

    ranked: list[ScoredCandidate] = []
    for cand in candidates:
        components = {k: v for k, v in cand.components.items() if v is not None}

        unknown = set(components) - set(weights)
        if unknown:
            raise ConfigError(
                f"{cand.symbol}: score families not in scoring.weights: {sorted(unknown)}"
            )

        out_of_range = {k: v for k, v in components.items() if not 0.0 <= v <= 1.0}
        if out_of_range:
            raise ValueError(
                f"{cand.symbol}: family scores must be absolute 0..1, got "
                f"{out_of_range}. Do not rescale the pool - see rank()."
            )

        available = sum(weights[k] for k in components)
        if available <= 0:
            continue

        composite = sum(weights[k] * v for k, v in components.items()) / available
        coverage = available / sum(weights.values())

        if min_coverage is not None and coverage < min_coverage:
            continue

        ranked.append(
            ScoredCandidate(
                symbol=cand.symbol,
                composite=composite,
                components=components,
                families_used=sorted(components),
                entry=cand.entry,
                stop=cand.stop,
                reason=getattr(cand, "reason", ""),
                coverage=coverage,
            )
        )

    return sorted(ranked, key=lambda c: c.composite, reverse=True)
