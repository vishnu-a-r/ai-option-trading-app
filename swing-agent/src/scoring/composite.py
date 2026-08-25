"""Composite ranking across the five signal families."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ScoredCandidate:
    symbol: str
    composite: float
    components: dict[str, float]
    entry: float
    stop: float
    targets: list[float]
    risk_reward: float
    qty: int
    reason: str


def validate_weights(cfg: dict) -> None:
    """Weights must sum to 1.0. Fail loudly at load, not silently at rank time."""


def rank(candidates: list, cfg: dict) -> list[ScoredCandidate]:
    """Weighted blend of technical_setup, fundamental, institutional,
    futures_confirmation, relative_strength.

    Normalize each family to 0..1 before weighting - raw scales differ and an
    unnormalized blend silently lets one family dominate.
    """
