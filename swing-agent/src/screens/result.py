"""The verdict a screen returns.

Lives in its own module rather than inside long_pullback.py: the short screen
used to import it from there, and a shared type should not be owned by one of
its consumers.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SetupResult:
    symbol: str
    passed: bool
    gate_failures: list[str] = field(default_factory=list)  # why it was rejected
    confirmations: dict[str, float] = field(default_factory=dict)  # scored, 0..1
    entry: float | None = None
    stop: float | None = None
    targets: list[float] = field(default_factory=list)
    reason: str = ""
