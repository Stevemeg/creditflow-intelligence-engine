"""
Tests for rule_loader.py: fail-fast schema validation of rules.yaml.
Covers every edge case explicitly named in the brief: malformed YAML,
duplicate ids, invalid operators, missing required keys, invalid impact
values, invalid rule structures, and duplicate config entries.
"""
import pytest

from engine.exceptions import ConfigurationError, RuleLoadError
from engine.rule_loader import load_rules


def _write(tmp_path, content, name="rules.yaml"):
    path = tmp_path / name
    path.write_text(content)
    return path


class TestMalformedYaml:
    def test_unclosed_bracket_raises_rule_load_error(self, tmp_path):
        path = _write(tmp_path, "gap_rules: [unclosed")
        with pytest.raises(RuleLoadError):
            load_rules(path)

    def test_empty_file_raises(self, tmp_path):
        path = _write(tmp_path, "")
        with pytest.raises(RuleLoadError):
            load_rules(path)

    def test_non_mapping_top_level_raises(self, tmp_path):
        path = _write(tmp_path, "- just\n- a\n- list\n")
        with pytest.raises(RuleLoadError):
            load_rules(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RuleLoadError):
            load_rules(tmp_path / "does_not_exist.yaml")


class TestDuplicateIds:
    def test_duplicate_id_within_gap_rules_raises(self, tmp_path):
        content = """
gap_rules:
  - id: dup
    field: a
    operator: gt
    value: 1
    impact: high
    estimated_score_gain: 10
    action_template: "x"
  - id: dup
    field: b
    operator: gt
    value: 1
    impact: low
    estimated_score_gain: 5
    action_template: "y"
eligibility_rules: []
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="Duplicate rule id"):
            load_rules(path)

    def test_duplicate_id_across_gap_and_eligibility_raises(self, tmp_path):
        content = """
gap_rules:
  - id: shared_id
    field: a
    operator: gt
    value: 1
    impact: high
    estimated_score_gain: 10
    action_template: "x"
eligibility_rules:
  - name: g1
    logic: AND
    rules:
      - id: shared_id
        field: b
        operator: gt
        value: 1
        message: "x"
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="Duplicate rule id"):
            load_rules(path)

    def test_duplicate_id_within_eligibility_subrules_raises(self, tmp_path):
        content = """
gap_rules: []
eligibility_rules:
  - name: g1
    logic: AND
    rules:
      - id: dup_sub
        field: a
        operator: gt
        value: 1
        message: "x"
      - id: dup_sub
        field: b
        operator: gt
        value: 1
        message: "y"
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="Duplicate rule id"):
            load_rules(path)


class TestInvalidOperators:
    def test_unknown_operator_in_gap_rule_raises_at_load_time(self, tmp_path):
        content = """
gap_rules:
  - id: x
    field: a
    operator: frobnicate
    value: 1
    impact: high
    estimated_score_gain: 10
    action_template: "x"
eligibility_rules: []
"""
        path = _write(tmp_path, content)
        with pytest.raises(Exception):  # OperatorNotSupportedError, a RuleEngineError
            load_rules(path)

    def test_unknown_operator_in_eligibility_rule_raises_at_load_time(self, tmp_path):
        content = """
gap_rules: []
eligibility_rules:
  - name: g1
    logic: AND
    rules:
      - id: x
        field: a
        operator: frobnicate
        message: "x"
"""
        path = _write(tmp_path, content)
        with pytest.raises(Exception):
            load_rules(path)


class TestMissingRequiredKeys:
    def test_gap_rule_missing_action_template_raises(self, tmp_path):
        content = """
gap_rules:
  - id: x
    field: a
    operator: gt
    value: 1
    impact: high
    estimated_score_gain: 10
eligibility_rules: []
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="missing required keys"):
            load_rules(path)

    def test_eligibility_subrule_missing_message_raises(self, tmp_path):
        content = """
gap_rules: []
eligibility_rules:
  - name: g1
    logic: AND
    rules:
      - id: x
        field: a
        operator: gt
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="missing required keys"):
            load_rules(path)

    def test_eligibility_group_missing_logic_raises(self, tmp_path):
        content = """
gap_rules: []
eligibility_rules:
  - name: g1
    rules:
      - id: x
        field: a
        operator: gt
        value: 1
        message: "x"
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="missing required key"):
            load_rules(path)


class TestInvalidImpactValues:
    def test_invalid_impact_string_raises(self, tmp_path):
        content = """
gap_rules:
  - id: x
    field: a
    operator: gt
    value: 1
    impact: catastrophic
    estimated_score_gain: 10
    action_template: "x"
eligibility_rules: []
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="invalid impact"):
            load_rules(path)


class TestInvalidRuleStructures:
    def test_gap_rules_not_a_list_raises(self, tmp_path):
        content = "gap_rules: not_a_list\neligibility_rules: []\n"
        path = _write(tmp_path, content)
        with pytest.raises(RuleLoadError, match="must be a list"):
            load_rules(path)

    def test_eligibility_rules_not_a_list_raises(self, tmp_path):
        content = "gap_rules: []\neligibility_rules: not_a_list\n"
        path = _write(tmp_path, content)
        with pytest.raises(RuleLoadError, match="must be a list"):
            load_rules(path)

    def test_eligibility_group_entry_not_a_mapping_raises(self, tmp_path):
        content = "gap_rules: []\neligibility_rules:\n  - just_a_string\n"
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="must be a mapping"):
            load_rules(path)

    def test_eligibility_subrule_entry_not_a_mapping_raises(self, tmp_path):
        content = """
gap_rules: []
eligibility_rules:
  - name: g1
    logic: AND
    rules:
      - just_a_string
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="must be a mapping"):
            load_rules(path)

    def test_gap_rule_entry_not_a_mapping_raises(self, tmp_path):
        content = "gap_rules:\n  - just_a_string\neligibility_rules: []\n"
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="must be a mapping"):
            load_rules(path)

    def test_negative_weight_on_eligibility_subrule_raises(self, tmp_path):
        content = """
gap_rules: []
eligibility_rules:
  - name: g1
    logic: AND
    rules:
      - id: x
        field: a
        operator: gt
        value: 1
        message: "x"
        weight: -1
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="invalid weight"):
            load_rules(path)

    def test_non_numeric_weight_on_eligibility_subrule_raises(self, tmp_path):
        content = """
gap_rules: []
eligibility_rules:
  - name: g1
    logic: AND
    rules:
      - id: x
        field: a
        operator: gt
        value: 1
        message: "x"
        weight: "heavy"
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="invalid weight"):
            load_rules(path)

    def test_negative_estimated_score_gain_raises(self, tmp_path):
        content = """
gap_rules:
  - id: x
    field: a
    operator: gt
    value: 1
    impact: high
    estimated_score_gain: -10
    action_template: "x"
eligibility_rules: []
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="estimated_score_gain"):
            load_rules(path)

    def test_zero_estimated_score_gain_raises(self, tmp_path):
        content = """
gap_rules:
  - id: x
    field: a
    operator: gt
    value: 1
    impact: high
    estimated_score_gain: 0
    action_template: "x"
eligibility_rules: []
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="estimated_score_gain"):
            load_rules(path)

    def test_non_integer_estimated_score_gain_raises(self, tmp_path):
        content = """
gap_rules:
  - id: x
    field: a
    operator: gt
    value: 1
    impact: high
    estimated_score_gain: "ten"
    action_template: "x"
eligibility_rules: []
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="estimated_score_gain"):
            load_rules(path)

    def test_empty_eligibility_rules_list_in_group_raises(self, tmp_path):
        content = """
gap_rules: []
eligibility_rules:
  - name: g1
    logic: AND
    rules: []
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="non-empty"):
            load_rules(path)

    def test_invalid_group_logic_raises(self, tmp_path):
        content = """
gap_rules: []
eligibility_rules:
  - name: g1
    logic: XOR
    rules:
      - id: x
        field: a
        operator: gt
        value: 1
        message: "x"
"""
        path = _write(tmp_path, content)
        with pytest.raises(ConfigurationError, match="invalid logic"):
            load_rules(path)


class TestEmptyRuleSets:
    def test_empty_gap_and_eligibility_rules_load_successfully(self, tmp_path):
        content = "gap_rules: []\neligibility_rules: []\n"
        path = _write(tmp_path, content)
        rule_set = load_rules(path)
        assert rule_set.gap_rules == []
        assert rule_set.eligibility_rules == []


class TestValidConfigLoadsSuccessfully:
    def test_real_rules_yaml_loads_without_error(self):
        from pathlib import Path

        real_path = Path(__file__).parent.parent / "rules.yaml"
        rule_set = load_rules(real_path)
        assert len(rule_set.gap_rules) == 5
        assert len(rule_set.eligibility_rules) == 1
        assert len(rule_set.eligibility_rules[0].rules) == 6
