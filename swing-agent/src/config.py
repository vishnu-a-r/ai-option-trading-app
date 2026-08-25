"""Config loading and validation.

`strategy.yaml` is the only place a number lives, which makes loading it the
only place a wrong number can be caught. Everything here fails at load, loudly,
rather than at rank time on a Tuesday.

Two distinct jobs:

  * load()    - structural and cross-consistency checks. Refuses a config whose
                numbers contradict each other.
  * require() - the null sentinel guard. Some values are deliberately null
                pending calibration; this turns "not yet decided" into a hard
                stop at the point of use instead of a silently skipped gate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WEIGHT_TOLERANCE = 1e-9

REQUIRED_BLOCKS = [
    "long_pullback",
    "fundamental",
    "data_quality",
    "institutional",
    "futures",
    "scoring",
    "risk",
]

REQUIRED_RISK_KEYS = [
    "capital_inr",
    "risk_per_trade_pct",
    "atr_period",
    "atr_stop_buffer",
    "max_position_pct_of_capital",
    "max_concurrent_positions",
    "max_sector_risk_pct",
    "max_sector_exposure_pct",
    "max_deployed_pct_of_capital",
    "max_aggregate_open_risk_pct",
    "time_stop_bars",
]


class ConfigError(ValueError):
    """The config is internally inconsistent or malformed."""


class UnresolvedConfig(ConfigError):
    """A deliberately-null value was read at the point it is needed.

    Not a bug and not a missing key - it means a calibration step has not
    happened yet. See the TODO comments in strategy.yaml.
    """


def load(path: str | Path) -> dict:
    """Parse and validate strategy.yaml. Raises ConfigError on any problem."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config not found: {path}")

    with path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path} did not parse to a mapping")

    missing = [b for b in REQUIRED_BLOCKS if b not in cfg]
    if missing:
        raise ConfigError(f"missing config blocks: {missing}")

    _validate_weights(cfg)
    _validate_risk(cfg)
    return cfg


def _validate_weights(cfg: dict) -> None:
    weights = cfg["scoring"].get("weights")
    if not weights:
        raise ConfigError("scoring.weights is empty")

    bad = {k: v for k, v in weights.items() if not isinstance(v, (int, float)) or v < 0}
    if bad:
        raise ConfigError(f"scoring.weights must be non-negative numbers: {bad}")

    total = sum(weights.values())
    if abs(total - 1.0) > WEIGHT_TOLERANCE:
        raise ConfigError(
            f"scoring.weights must sum to 1.0, got {total!r} from {weights}"
        )


def _validate_risk(cfg: dict) -> None:
    """Cross-consistency, not just presence.

    Any one of these numbers is defensible alone; the failure mode is two of
    them asserting different things about the same portfolio. Raising
    max_concurrent_positions without touching the aggregate risk cap is the
    obvious way in, and nothing downstream would notice - the position count
    gate and the risk gate would simply disagree about how many positions the
    account may hold.
    """
    risk = cfg["risk"]

    missing = [k for k in REQUIRED_RISK_KEYS if k not in risk]
    if missing:
        raise ConfigError(f"missing risk keys: {missing}")

    per_trade = risk["risk_per_trade_pct"]
    positions = risk["max_concurrent_positions"]
    aggregate = risk["max_aggregate_open_risk_pct"]
    sector_risk = risk["max_sector_risk_pct"]
    position_cap = risk["max_position_pct_of_capital"]
    deployed_cap = risk["max_deployed_pct_of_capital"]

    for name, value in [
        ("capital_inr", risk["capital_inr"]),
        ("risk_per_trade_pct", per_trade),
        ("max_concurrent_positions", positions),
        ("atr_period", risk["atr_period"]),
    ]:
        if not value or value <= 0:
            raise ConfigError(f"risk.{name} must be positive, got {value!r}")

    if risk["atr_stop_buffer"] < 0:
        raise ConfigError("risk.atr_stop_buffer must be >= 0")

    if per_trade * positions > aggregate:
        raise ConfigError(
            f"risk caps contradict: {positions} positions at {per_trade}% each is "
            f"{per_trade * positions}% of capital at risk, but "
            f"max_aggregate_open_risk_pct is {aggregate}%. Raise the aggregate cap "
            f"or lower max_concurrent_positions."
        )

    if sector_risk > aggregate:
        raise ConfigError(
            f"risk.max_sector_risk_pct ({sector_risk}%) exceeds "
            f"max_aggregate_open_risk_pct ({aggregate}%), so the sector cap can "
            f"never bind."
        )

    if position_cap > deployed_cap:
        raise ConfigError(
            f"risk.max_position_pct_of_capital ({position_cap}%) exceeds "
            f"max_deployed_pct_of_capital ({deployed_cap}%): a single position "
            f"would overdraw the account."
        )


def require(cfg: dict, dotted_path: str) -> Any:
    """Read a config value that must not be null. Raises UnresolvedConfig if it is.

    Use this for every value strategy.yaml leaves deliberately null -
    fundamental.long_gate.* and risk.sector_taxonomy.

    Why an accessor rather than a plain lookup: `roce > None` does raise, but
    that is not the shape the code takes under an edge case. The idiom that
    gets written is

        if min_roce and roce > min_roce:      # None is falsy -> gate skipped

    which passes the stock instead of stopping the run. That is the exact
    failure the null was chosen to prevent, and a bare lookup cannot prevent it.
    """
    node: Any = cfg
    walked: list[str] = []
    for part in dotted_path.split("."):
        walked.append(part)
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(f"no such config key: {'.'.join(walked)}")
        node = node[part]

    if node is None:
        raise UnresolvedConfig(
            f"{dotted_path} is null - it needs a calibration pass before this code "
            f"path can run. See the TODO comment in strategy.yaml. Do not "
            f"substitute a plausible default: a guessed threshold silently filters "
            f"the universe and every number downstream inherits it."
        )
    return node
