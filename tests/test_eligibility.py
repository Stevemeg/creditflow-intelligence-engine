"""
Tests for eligibility mode: all-pass, multi-failure, missing fields,
boundary values, AND group logic, and the bonus weighted risk score.
"""
import json
from pathlib import Path

import pytest

from engine.eligibility_engine import evaluate_eligibility
from engine.rule_loader import load_rules

SAMPLE_RULES_PATH = Path(__file__).parent.parent / "rules.yaml"
SAMPLE_PROFILE_PATH = Path(__file__).parent.parent / "sample_data" / "customer_profile.json"

VALID_PROFILE = {
    "customer_id": "X",
    "age": 30,
    "cibil_score": 700,
    "monthly_income": 60000,
    "existing_emis": 10000,
    "foir": 0.3,
    "employment_type": "salaried",
    "written_off_accounts": 0,
    "requested_amount": 300000,
}


@pytest.fixture(scope="module")
def rule_set():
    return load_rules(SAMPLE_RULES_PATH)


@pytest.fixture
def sample_profile():
    with open(SAMPLE_PROFILE_PATH) as f:
        return json.load(f)


class TestSampleInputMatchesBriefExactly:
    def test_not_eligible_due_to_low_score(self, rule_set, sample_profile):
        result = evaluate_eligibility(rule_set, sample_profile)
        assert result.eligible is False
        assert result.fail_reasons == ["cibil_score"]

    def test_every_rule_reported(self, rule_set, sample_profile):
        result = evaluate_eligibility(rule_set, sample_profile)
        rule_ids = {r.rule for r in result.rules}
        assert rule_ids == {
            "age",
            "cibil_score",
            "foir",
            "employment_type",
            "no_written_off_accounts",
            "loan_amount_cap",
        }

    def test_cibil_failure_has_specific_message(self, rule_set, sample_profile):
        result = evaluate_eligibility(rule_set, sample_profile)
        cibil_result = next(r for r in result.rules if r.rule == "cibil_score")
        assert cibil_result.passed is False
        assert "650" in cibil_result.reason


class TestAllRulesPass:
    def test_eligible_true_and_no_fail_reasons(self, rule_set):
        result = evaluate_eligibility(rule_set, VALID_PROFILE)
        assert result.eligible is True
        assert result.fail_reasons == []
        assert all(r.passed for r in result.rules)
        assert all(r.reason is None for r in result.rules)


class TestMultipleRulesFail:
    def test_all_failures_listed(self, rule_set):
        bad_profile = dict(
            VALID_PROFILE,
            age=15,  # fails age
            cibil_score=500,  # fails cibil_score
            written_off_accounts=2,  # fails no_written_off_accounts
        )
        result = evaluate_eligibility(rule_set, bad_profile)
        assert result.eligible is False
        assert set(result.fail_reasons) == {"age", "cibil_score", "no_written_off_accounts"}
        for rule_id in result.fail_reasons:
            r = next(r for r in result.rules if r.rule == rule_id)
            assert r.passed is False
            assert r.reason  # every failure has a non-empty reason


class TestMissingField:
    def test_missing_field_reported_as_failure_not_crash(self, rule_set):
        incomplete_profile = {"customer_id": "X", "age": 30}  # everything else missing
        result = evaluate_eligibility(rule_set, incomplete_profile)
        assert result.eligible is False
        cibil_result = next(r for r in result.rules if r.rule == "cibil_score")
        assert cibil_result.passed is False
        assert "missing" in cibil_result.reason.lower()

    def test_empty_customer_profile_does_not_crash(self, rule_set):
        result = evaluate_eligibility(rule_set, {})
        assert result.eligible is False
        assert len(result.rules) == 6
        assert all(not r.passed for r in result.rules)


class TestBoundaryValues:
    """Explicit boundary cases named in the brief."""

    @pytest.mark.parametrize("age,expected", [(21, True), (60, True), (20, False), (61, False)])
    def test_age_boundaries(self, rule_set, age, expected):
        profile = dict(VALID_PROFILE, age=age)
        result = evaluate_eligibility(rule_set, profile)
        rule = next(r for r in result.rules if r.rule == "age")
        assert rule.passed is expected

    @pytest.mark.parametrize("score,expected", [(650, True), (649, False)])
    def test_cibil_score_boundaries(self, rule_set, score, expected):
        profile = dict(VALID_PROFILE, cibil_score=score)
        result = evaluate_eligibility(rule_set, profile)
        rule = next(r for r in result.rules if r.rule == "cibil_score")
        assert rule.passed is expected

    @pytest.mark.parametrize("foir_value,expected", [(0.5, True), (0.51, False)])
    def test_foir_boundaries(self, rule_set, foir_value, expected):
        profile = dict(VALID_PROFILE, foir=foir_value)
        result = evaluate_eligibility(rule_set, profile)
        rule = next(r for r in result.rules if r.rule == "foir")
        assert rule.passed is expected

    def test_loan_amount_cap_at_exact_boundary(self, rule_set):
        # requested_amount == monthly_income * 10 exactly -> should pass (lte)
        profile = dict(VALID_PROFILE, monthly_income=50000, requested_amount=500000)
        result = evaluate_eligibility(rule_set, profile)
        rule = next(r for r in result.rules if r.rule == "loan_amount_cap")
        assert rule.passed is True

    def test_loan_amount_cap_just_over_boundary(self, rule_set):
        profile = dict(VALID_PROFILE, monthly_income=50000, requested_amount=500001)
        result = evaluate_eligibility(rule_set, profile)
        rule = next(r for r in result.rules if r.rule == "loan_amount_cap")
        assert rule.passed is False


class TestAndGroupLogic:
    def test_single_failure_in_and_group_fails_whole_group(self, rule_set):
        # Even though 5 of 6 rules pass, AND logic means one failure
        # makes the customer ineligible overall.
        profile = dict(VALID_PROFILE, employment_type="unemployed")
        result = evaluate_eligibility(rule_set, profile)
        assert result.eligible is False
        passed_count = sum(1 for r in result.rules if r.passed)
        assert passed_count == 5


class TestWeightedRiskScore:
    """Bonus feature: risk_score = (sum of weights of failed rules /
    sum of all weights) * 100."""

    def test_risk_score_zero_when_all_pass(self, rule_set):
        result = evaluate_eligibility(rule_set, VALID_PROFILE)
        assert result.risk_score == 0.0

    def test_risk_score_one_hundred_when_all_fail(self, rule_set):
        result = evaluate_eligibility(rule_set, {})
        assert result.risk_score == 100.0

    def test_risk_score_matches_manual_calculation(self, rule_set, sample_profile):
        # In rules.yaml: cibil_score has weight 2.0; total weight across
        # all 6 rules is 1.0+2.0+1.5+0.5+2.0+1.0 = 8.0. Only cibil_score
        # fails for the brief's sample profile -> risk = 2.0/8.0*100 = 25.0
        result = evaluate_eligibility(rule_set, sample_profile)
        assert result.risk_score == 25.0

    def test_risk_score_can_be_disabled(self, rule_set, sample_profile):
        result = evaluate_eligibility(rule_set, sample_profile, include_risk_score=False)
        assert result.risk_score is None
        assert "risk_score" not in result.to_dict()


class TestOrGroupLogicFutureReadiness:
    """The brief requires the architecture to support OR group logic
    even though the sample rules.yaml only uses AND. This test proves
    OR works correctly by loading a custom config with an OR group --
    no engine code change was needed to make this pass."""

    @pytest.fixture
    def or_rule_set(self, tmp_path):
        yaml_content = """
gap_rules: []
eligibility_rules:
  - name: or_test_group
    logic: OR
    rules:
      - id: has_good_score
        field: cibil_score
        operator: gte
        value: 750
        message: "Score below 750"
      - id: has_collateral
        field: has_collateral
        operator: eq
        value: true
        message: "No collateral provided"
"""
        path = tmp_path / "or_rules.yaml"
        path.write_text(yaml_content)
        return load_rules(path)

    def test_or_group_passes_if_only_one_subrule_passes(self, or_rule_set):
        # Fails has_good_score (600 < 750) but passes has_collateral.
        profile = {"cibil_score": 600, "has_collateral": True}
        result = evaluate_eligibility(or_rule_set, profile, include_risk_score=False)
        assert result.eligible is True
        # Individual rule results are still both reported, regardless of
        # the group passing overall -- detailed reasoning is preserved.
        assert len(result.rules) == 2

    def test_or_group_fails_if_no_subrule_passes(self, or_rule_set):
        profile = {"cibil_score": 600, "has_collateral": False}
        result = evaluate_eligibility(or_rule_set, profile, include_risk_score=False)
        assert result.eligible is False
        assert set(result.fail_reasons) == {"has_good_score", "has_collateral"}


class TestNextStep:
    def test_next_step_present_when_ineligible(self, rule_set, sample_profile):
        result = evaluate_eligibility(rule_set, sample_profile)
        assert result.next_step
        assert isinstance(result.next_step, str)

    def test_next_step_absent_when_eligible(self, rule_set):
        result = evaluate_eligibility(rule_set, VALID_PROFILE)
        assert result.next_step is None
        assert "next_step" not in result.to_dict()

    def test_next_step_falls_back_to_first_failure_reason_when_not_cibil(self, rule_set):
        """When cibil_score isn't among the failures, next_step should
        fall back to the first failed rule's own message rather than
        the CIBIL-specific hint."""
        profile = dict(VALID_PROFILE, employment_type="unemployed")
        result = evaluate_eligibility(rule_set, profile)
        assert result.fail_reasons == ["employment_type"]
        assert result.next_step == "Employment type must be salaried or self-employed"


class TestInvalidInputType:
    def test_non_dict_customer_profile_raises_configuration_error(self, rule_set):
        from engine.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError):
            evaluate_eligibility(rule_set, ["not", "a", "dict"])
