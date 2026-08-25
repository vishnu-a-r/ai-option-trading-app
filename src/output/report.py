"""Daily output: JSON for the record, readable summary for the human."""
from __future__ import annotations
from pathlib import Path


def write_json(candidates, near_misses, path: Path) -> None:
    """Full detail including every component score."""


def write_summary(candidates, near_misses, path: Path) -> None:
    """Per candidate: side, entry trigger, stop, target(s), R:R, qty, one-line
    reason, and the score breakdown.

    Then the near-misses with the specific failing gate - these are often more
    informative than the passes when tuning thresholds.
    """


def notify(summary: str) -> None:
    """Alert only. See run_daily.py on why this never places an order."""
