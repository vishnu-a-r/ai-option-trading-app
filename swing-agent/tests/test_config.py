"""Config validation.

The point of these is the cross-consistency checks: any single number in the
risk block is defensible alone, and the failure mode is two of them asserting
different things about the same portfolio.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from src.config import ConfigError, UnresolvedConfig, load, require

REAL = "config/strategy.yaml"


@pytest.fixture
def cfg():
    return load(REAL)


def write(tmp_path, cfg):
    p = tmp_path / "strategy.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


class TestTheShippedConfig:
    """The file in the repo must actually pass its own validator."""

    def test_it_loads(self, cfg):
        assert cfg["risk"]["capital_inr"] == 200_000

    def test_weights_sum_to_one(self, cfg):
        assert sum(cfg["scoring"]["weights"].values()) == pytest.approx(1.0)

    def test_the_long_only_blocks_are_gone(self, cfg):
        assert "short_breakdown" not in cfg
        assert "short_flag" not in cfg["fundamental"]
        assert "top_n_short" not in cfg["scoring"]


class TestStructure:
    def test_missing_file_is_reported(self):
        with pytest.raises(ConfigError, match="not found"):
            load("config/does-not-exist.yaml")

    def test_missing_block_is_reported(self, cfg, tmp_path):
        broken = copy.deepcopy(cfg)
        del broken["scoring"]
        with pytest.raises(ConfigError, match="missing config blocks"):
            load(write(tmp_path, broken))

    def test_non_mapping_file_is_reported(self, tmp_path):
        p = tmp_path / "strategy.yaml"
        p.write_text("- just\n- a list\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="mapping"):
            load(p)


class TestWeights:
    @pytest.mark.parametrize("total", [0.95, 1.05])
    def test_weights_not_summing_to_one_are_refused(self, cfg, tmp_path, total):
        broken = copy.deepcopy(cfg)
        broken["scoring"]["weights"] = {"technical_setup": total}
        with pytest.raises(ConfigError, match="must sum to 1.0"):
            load(write(tmp_path, broken))

    def test_the_error_names_the_actual_sum(self, cfg, tmp_path):
        broken = copy.deepcopy(cfg)
        broken["scoring"]["weights"] = {"a": 0.5, "b": 0.4}
        with pytest.raises(ConfigError, match="0.9"):
            load(write(tmp_path, broken))

    def test_negative_weight_is_refused(self, cfg, tmp_path):
        broken = copy.deepcopy(cfg)
        broken["scoring"]["weights"] = {"a": 1.5, "b": -0.5}
        with pytest.raises(ConfigError, match="non-negative"):
            load(write(tmp_path, broken))


class TestRiskCrossConsistency:
    """Each of these configs is individually plausible and jointly wrong."""

    def test_more_positions_than_the_aggregate_risk_cap_allows(self, cfg, tmp_path):
        broken = copy.deepcopy(cfg)
        broken["risk"]["max_concurrent_positions"] = 10  # 10 x 1% = 10% vs a 6% cap
        with pytest.raises(ConfigError, match="risk caps contradict"):
            load(write(tmp_path, broken))

    def test_the_shipped_config_sits_exactly_at_the_boundary(self, cfg):
        r = cfg["risk"]
        assert r["risk_per_trade_pct"] * r["max_concurrent_positions"] == r["max_aggregate_open_risk_pct"]

    def test_sector_risk_cap_above_the_aggregate_cap_is_refused(self, cfg, tmp_path):
        broken = copy.deepcopy(cfg)
        broken["risk"]["max_sector_risk_pct"] = 8  # aggregate is 6
        with pytest.raises(ConfigError, match="never bind"):
            load(write(tmp_path, broken))

    def test_position_cap_above_the_deployment_cap_is_refused(self, cfg, tmp_path):
        broken = copy.deepcopy(cfg)
        broken["risk"]["max_position_pct_of_capital"] = 120
        with pytest.raises(ConfigError, match="overdraw"):
            load(write(tmp_path, broken))

    def test_missing_risk_key_is_reported(self, cfg, tmp_path):
        broken = copy.deepcopy(cfg)
        del broken["risk"]["max_deployed_pct_of_capital"]
        with pytest.raises(ConfigError, match="missing risk keys"):
            load(write(tmp_path, broken))

    @pytest.mark.parametrize("key", ["capital_inr", "risk_per_trade_pct", "atr_period"])
    def test_non_positive_values_are_refused(self, cfg, tmp_path, key):
        broken = copy.deepcopy(cfg)
        broken["risk"][key] = 0
        with pytest.raises(ConfigError, match="must be positive"):
            load(write(tmp_path, broken))

    def test_negative_atr_buffer_is_refused(self, cfg, tmp_path):
        broken = copy.deepcopy(cfg)
        broken["risk"]["atr_stop_buffer"] = -0.5
        with pytest.raises(ConfigError, match="atr_stop_buffer"):
            load(write(tmp_path, broken))


class TestRequire:
    """The null sentinel guard."""

    def test_a_set_value_comes_back(self, cfg):
        assert require(cfg, "risk.atr_period") == 14

    def test_nested_path_walks_correctly(self, cfg):
        assert require(cfg, "long_pullback.momentum.rsi_min") == 30

    def test_sector_taxonomy_is_pinned_now(self, cfg):
        """Was null; pinned to NSE's Industry column once the data supplied one."""
        assert require(cfg, "risk.sector_taxonomy") == "nse_industry"

    @pytest.mark.parametrize(
        "key", ["min_roce", "min_roe", "max_debt_to_equity", "min_ocf_to_pat"]
    )
    def test_every_null_long_gate_threshold_raises(self, cfg, key):
        with pytest.raises(UnresolvedConfig):
            require(cfg, f"fundamental.long_gate.{key}")

    def test_the_message_says_not_to_substitute_a_default(self, cfg):
        with pytest.raises(UnresolvedConfig, match="Do not"):
            require(cfg, "fundamental.long_gate.min_roce")

    def test_a_genuinely_absent_key_is_a_different_error(self, cfg):
        with pytest.raises(ConfigError, match="no such config key") as exc:
            require(cfg, "risk.no_such_thing")
        assert not isinstance(exc.value, UnresolvedConfig)

    def test_zero_is_not_treated_as_unresolved(self, cfg):
        """The bug this whole accessor exists to prevent, in miniature."""
        probe = {"risk": {"atr_stop_buffer": 0}}
        assert require(probe, "risk.atr_stop_buffer") == 0
