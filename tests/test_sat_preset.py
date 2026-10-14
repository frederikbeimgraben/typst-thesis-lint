from __future__ import annotations

from typing import TYPE_CHECKING

from thesis_lint import config as config_module
from thesis_lint.registry import all_rules

if TYPE_CHECKING:
    from pathlib import Path


def test_preset_enables_all_sat_rules_with_the_default_values(tmp_path: Path) -> None:
    (tmp_path / "lint.toml").write_text('extends = ["sat-meti"]\n', encoding="utf-8")
    config = config_module.load(tmp_path)
    sat_rules = {rule_id: rule for rule_id, rule in all_rules().items() if rule.pack == "sat"}
    assert sat_rules
    for rule_id, rule in sat_rules.items():
        assert rule_id in config.rules, rule_id
        assert config.rules[rule_id].params == rule.params, rule_id
