"""
Tests for gap analysis mode: rule firing, sorting order (explicitly
required to be tested per the brief), action template substitution,
total score gain, and edge cases (missing/null fields, empty report).
"""
import json
import tempfile
from pathlib import Path

import pytest

from engine.gap_analyser import analyse_gaps
from engine.rule_loader import load_rules

SAMPLE_RULES_PATH = Path(__file__).parent.parent / "rules.yaml"
SAMPLE_REPORT_PATH = Path(__file__).parent.parent / "sample_data" / "credit_report.json"


@pytest.fixture(scope="module")
def rule_set():
    return load_rules(SAMPLE_RULES_PATH)


@pytest.fixture
def sample_report():
    with open(SAMPLE_REPORT_PATH) as f:
        return json.load(f)


class TestSampleInputMatchesBriefExactly:
    """Locks in the exact expected output the brief specifies for its
    sample credit_report.json, so a future change to rules.yaml or the
    engine that breaks this contract is caught immediately."""

    def test_gaps_found_count(self, rule_set, sample_report):
        result = analyse_gaps(rule_set, sample_report)
        assert result.gaps_found == 3

    def test_total_potential_score_gain(self, rule_set, sample_report):
        result = analyse_gaps(rule_set, sample_report)
        assert result.total_potential_score_gain == 70

    def test_fired_gap_ids_in_order(self, rule_set, sample_report):
        result = analyse_gaps(rule_set, sample_report)
        assert [g.id for g in result.gaps] == [
            "high_utilisation",
            "missed_payments",
            "short_credit_age",
        ]

    def test_action_text_for_high_utilisation(self, rule_set, sample_report):
        result = analyse_gaps(rule_set, sample_report)
        gap = next(g for g in result.gaps if g.id == "high_utilisation")
        assert gap.action == "Reduce credit card utilisation from 87% to below 30%"


class TestAllGapRulesFire:
    def test_all_five_rules_fire_when_every_factor_is_bad(self, rule_set):
        report = {
            "customer_id": "BAD001",
            "credit_utilisation_pct": 95,
            "missed_payments_12m": 4,
            "written_off_accounts": 2,
            "credit_age_months": 6,
            "hard_enquiries_6m": 8,
        }
        result = analyse_gaps(rule_set, report)
        assert result.gaps_found == 5
        assert {g.id for g in result.gaps} == {
            "high_utilisation",
            "missed_payments",
            "written_off_account",
            "short_credit_age",
            "too_many_enquiries",
        }


class TestNoGapsFound:
    def test_perfect_profile_triggers_no_gaps(self, rule_set):
        report = {
            "customer_id": "GOOD001",
            "credit_utilisation_pct": 10,
            "missed_payments_12m": 0,
            "written_off_accounts": 0,
            "credit_age_months": 120,
            "hard_enquiries_6m": 1,
        }
        result = analyse_gaps(rule_set, report)
        assert result.gaps_found == 0
        assert result.gaps == []
        assert result.total_potential_score_gain == 0

    def test_empty_credit_report_triggers_no_gaps(self, rule_set):
        result = analyse_gaps(rule_set, {})
        assert result.gaps_found == 0
        assert result.gaps == []


class TestSortingOrder:
    """Explicit requirement: sort by impact (high -> medium -> low),
    then by estimated_score_gain descending within the same impact."""

    def test_high_impact_sorted_before_medium_and_low(self, rule_set):
        report = {
            "customer_id": "X",
            "credit_utilisation_pct": 50,  # high impact, gain 35
            "missed_payments_12m": 0,
            "written_off_accounts": 0,
            "credit_age_months": 10,  # medium impact, gain 10
            "hard_enquiries_6m": 5,  # medium impact, gain 10
        }
        result = analyse_gaps(rule_set, report)
        impacts = [g.impact for g in result.gaps]
        assert impacts[0] == "high"
        assert impacts.count("high") == 1
        assert all(i == "medium" for i in impacts[1:])

    def test_within_same_impact_sorted_by_gain_descending(self, rule_set):
        # Trigger two high-impact rules with different gains:
        # missed_payments (25) and written_off_account (40).
        # written_off_account should sort first despite being defined
        # second in rules.yaml, since 40 > 25.
        report = {
            "customer_id": "X",
            "credit_utilisation_pct": 10,
            "missed_payments_12m": 1,  # high, gain 25
            "written_off_accounts": 1,  # high, gain 40
            "credit_age_months": 100,
            "hard_enquiries_6m": 0,
        }
        result = analyse_gaps(rule_set, report)
        high_impact_gaps = [g for g in result.gaps if g.impact == "high"]
        assert [g.id for g in high_impact_gaps] == ["written_off_account", "missed_payments"]
        gains = [g.estimated_score_gain for g in high_impact_gaps]
        assert gains == sorted(gains, reverse=True)

    def test_full_ordering_across_all_three_impact_levels(self, rule_set):
        report = {
            "customer_id": "X",
            "credit_utilisation_pct": 95,  # high, 35
            "missed_payments_12m": 3,  # high, 25
            "written_off_accounts": 1,  # high, 40
            "credit_age_months": 12,  # medium, 10
            "hard_enquiries_6m": 10,  # medium, 10
        }
        result = analyse_gaps(rule_set, report)
        ids_in_order = [g.id for g in result.gaps]
        # high-impact block (sorted by gain desc): written_off(40), high_util(35), missed(25)
        assert ids_in_order[:3] == ["written_off_account", "high_utilisation", "missed_payments"]
        # medium-impact block follows; both have gain 10, so relative
        # order between them is not asserted (stable sort keeps original
        # rules.yaml order: short_credit_age, too_many_enquiries)
        assert set(ids_in_order[3:]) == {"short_credit_age", "too_many_enquiries"}
        assert all(g.impact in ("high",) for g in result.gaps[:3])
        assert all(g.impact == "medium" for g in result.gaps[3:])


class TestActionTemplateSubstitution:
    def test_current_value_substituted(self, rule_set):
        report = {
            "customer_id": "X",
            "credit_utilisation_pct": 77,
            "missed_payments_12m": 0,
            "written_off_accounts": 0,
            "credit_age_months": 100,
            "hard_enquiries_6m": 0,
        }
        result = analyse_gaps(rule_set, report)
        gap = next(g for g in result.gaps if g.id == "high_utilisation")
        assert "77" in gap.action

    def test_missing_template_variable_does_not_crash(self):
        """If action_template references a field not present in the
        credit report, rendering must not raise -- the placeholder is
        left literally in the string instead."""
        yaml_content = """
gap_rules:
  - id: weird_rule
    field: some_field
    operator: gt
    value: 0
    impact: low
    estimated_score_gain: 5
    action_template: "Value is {current_value}, also see {totally_unknown_field}"
eligibility_rules: []
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            rs = load_rules(path)
            result = analyse_gaps(rs, {"some_field": 5})
            assert result.gaps_found == 1
            assert "5" in result.gaps[0].action
            assert "{totally_unknown_field}" in result.gaps[0].action
        finally:
            Path(path).unlink()

    def test_malformed_template_syntax_does_not_crash(self):
        """A genuinely malformed action_template (e.g. an unclosed
        brace -- a config-authoring mistake in rules.yaml) must not
        raise either; it falls back to the raw template string rather
        than crashing the entire analysis."""
        yaml_content = """
gap_rules:
  - id: malformed_template_rule
    field: some_field
    operator: gt
    value: 0
    impact: low
    estimated_score_gain: 5
    action_template: "Value is {current_value"
eligibility_rules: []
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            rs = load_rules(path)
            result = analyse_gaps(rs, {"some_field": 5})
            assert result.gaps_found == 1
            assert result.gaps[0].action == "Value is {current_value"
        finally:
            Path(path).unlink()

    def test_missing_field_plus_malformed_brace_together_does_not_crash(self):
        """Combines both failure modes: a {placeholder} with no matching
        key (triggers the safe-format fallback) AND a malformed/unclosed
        brace (triggers that fallback's own internal catch). Exercises
        the second-level except ValueError inside _safe_format."""
        from engine.gap_analyser import _render_action_template

        result = _render_action_template(
            "See {missing_field} and {current_value", 5, {}, "some_field"
        )
        assert result == "See {missing_field} and {current_value"


class TestNullAndMissingFields:
    def test_null_field_value_does_not_fire_rule(self, rule_set):
        report = {
            "customer_id": "X",
            "credit_utilisation_pct": None,
            "missed_payments_12m": 0,
            "written_off_accounts": 0,
            "credit_age_months": 100,
            "hard_enquiries_6m": 0,
        }
        result = analyse_gaps(rule_set, report)
        assert all(g.id != "high_utilisation" for g in result.gaps)

    def test_missing_field_does_not_fire_rule(self, rule_set):
        report = {"customer_id": "X"}  # every field absent
        result = analyse_gaps(rule_set, report)
        assert result.gaps_found == 0


class TestInvalidInputType:
    def test_non_dict_credit_report_raises_configuration_error(self, rule_set):
        from engine.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError):
            analyse_gaps(rule_set, ["not", "a", "dict"])

    def test_wrong_type_for_numeric_field_does_not_fire_rule(self, rule_set):
        """An operator-level type error (e.g. a string where a number
        is expected) is treated as 'this rule cannot fire', not a crash
        -- mirrors the null/missing-field handling above but for a
        present-but-wrong-typed value."""
        report = {
            "customer_id": "X",
            "credit_utilisation_pct": "eighty-seven percent",  # wrong type
            "missed_payments_12m": 0,
            "written_off_accounts": 0,
            "credit_age_months": 100,
            "hard_enquiries_6m": 0,
        }
        result = analyse_gaps(rule_set, report)
        assert all(g.id != "high_utilisation" for g in result.gaps)
