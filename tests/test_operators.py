"""
Tests for the operator registry: every operator in isolation, plus
registry-level behavior (unknown operator lookup, runtime registration).
"""
import pytest

from engine.exceptions import ConfigurationError, OperatorNotSupportedError
from engine.operators import OPERATORS, get_operator, register_operator


class TestComparisonOperators:
    def test_gt(self):
        assert OPERATORS["gt"](31, {"value": 30}, {}) is True
        assert OPERATORS["gt"](30, {"value": 30}, {}) is False
        assert OPERATORS["gt"](29, {"value": 30}, {}) is False

    def test_gte(self):
        assert OPERATORS["gte"](650, {"value": 650}, {}) is True
        assert OPERATORS["gte"](649, {"value": 650}, {}) is False
        assert OPERATORS["gte"](651, {"value": 650}, {}) is True

    def test_lt(self):
        assert OPERATORS["lt"](35, {"value": 36}, {}) is True
        assert OPERATORS["lt"](36, {"value": 36}, {}) is False

    def test_lte(self):
        assert OPERATORS["lte"](0.5, {"value": 0.5}, {}) is True
        assert OPERATORS["lte"](0.51, {"value": 0.5}, {}) is False

    def test_eq(self):
        assert OPERATORS["eq"](0, {"value": 0}, {}) is True
        assert OPERATORS["eq"]("salaried", {"value": "salaried"}, {}) is True
        assert OPERATORS["eq"](1, {"value": 0}, {}) is False

    def test_eq_rejects_bool_vs_numeric_match(self):
        """Regression test: Python's `True == 1` and `False == 0` must
        NOT cause a boolean field to satisfy a numeric equality check --
        a malformed `written_off_accounts: true` should never silently
        equal the threshold `written_off_accounts == 0`."""
        assert OPERATORS["eq"](True, {"value": 1}, {}) is False
        assert OPERATORS["eq"](False, {"value": 0}, {}) is False
        assert OPERATORS["eq"](1, {"value": True}, {}) is False
        assert OPERATORS["eq"](0, {"value": False}, {}) is False

    def test_eq_bool_vs_bool_still_works(self):
        assert OPERATORS["eq"](True, {"value": True}, {}) is True
        assert OPERATORS["eq"](False, {"value": False}, {}) is True
        assert OPERATORS["eq"](True, {"value": False}, {}) is False

    def test_neq(self):
        assert OPERATORS["neq"](1, {"value": 0}, {}) is True
        assert OPERATORS["neq"](0, {"value": 0}, {}) is False

    def test_neq_bool_vs_numeric_treated_as_not_equal(self):
        assert OPERATORS["neq"](False, {"value": 0}, {}) is True
        assert OPERATORS["neq"](True, {"value": 1}, {}) is True


class TestBetweenOperator:
    def test_within_range(self):
        assert OPERATORS["between"](29, {"min": 21, "max": 60}, {}) is True

    def test_at_lower_boundary_inclusive(self):
        assert OPERATORS["between"](21, {"min": 21, "max": 60}, {}) is True

    def test_at_upper_boundary_inclusive(self):
        assert OPERATORS["between"](60, {"min": 21, "max": 60}, {}) is True

    def test_below_range(self):
        assert OPERATORS["between"](20, {"min": 21, "max": 60}, {}) is False

    def test_above_range(self):
        assert OPERATORS["between"](61, {"min": 21, "max": 60}, {}) is False

    def test_missing_min_raises_configuration_error(self):
        with pytest.raises(ConfigurationError):
            OPERATORS["between"](30, {"max": 60, "id": "x"}, {})

    def test_missing_max_raises_configuration_error(self):
        with pytest.raises(ConfigurationError):
            OPERATORS["between"](30, {"min": 21, "id": "x"}, {})


class TestInNotInOperators:
    def test_in_matches(self):
        assert OPERATORS["in"]("salaried", {"values": ["salaried", "self_employed"]}, {}) is True

    def test_in_no_match(self):
        assert OPERATORS["in"]("unemployed", {"values": ["salaried", "self_employed"]}, {}) is False

    def test_in_missing_values_raises(self):
        with pytest.raises(ConfigurationError):
            OPERATORS["in"]("x", {"id": "x"}, {})

    def test_not_in_matches(self):
        assert OPERATORS["not_in"]("unemployed", {"values": ["salaried", "self_employed"]}, {}) is True

    def test_not_in_no_match(self):
        assert OPERATORS["not_in"]("salaried", {"values": ["salaried", "self_employed"]}, {}) is False

    def test_not_in_missing_values_raises(self):
        with pytest.raises(ConfigurationError):
            OPERATORS["not_in"]("x", {"id": "x"}, {})


class TestLteMultiplierOperator:
    def test_within_cap(self):
        rule = {"id": "x", "multiplier_field": "monthly_income", "multiplier": 10}
        profile = {"monthly_income": 60000}
        assert OPERATORS["lte_multiplier"](400000, rule, profile) is True

    def test_exceeds_cap(self):
        rule = {"id": "x", "multiplier_field": "monthly_income", "multiplier": 10}
        profile = {"monthly_income": 60000}
        assert OPERATORS["lte_multiplier"](700000, rule, profile) is False

    def test_at_exact_cap_boundary(self):
        rule = {"id": "x", "multiplier_field": "monthly_income", "multiplier": 10}
        profile = {"monthly_income": 60000}
        assert OPERATORS["lte_multiplier"](600000, rule, profile) is True

    def test_missing_multiplier_field_key_raises(self):
        rule = {"id": "x", "multiplier": 10}
        with pytest.raises(ConfigurationError):
            OPERATORS["lte_multiplier"](400000, rule, {"monthly_income": 60000})

    def test_missing_multiplier_key_raises(self):
        rule = {"id": "x", "multiplier_field": "monthly_income"}
        with pytest.raises(ConfigurationError):
            OPERATORS["lte_multiplier"](400000, rule, {"monthly_income": 60000})

    def test_referenced_field_missing_from_profile_raises(self):
        rule = {"id": "x", "multiplier_field": "monthly_income", "multiplier": 10}
        with pytest.raises(ConfigurationError):
            OPERATORS["lte_multiplier"](400000, rule, {})  # monthly_income absent


class TestNumericCoercion:
    """Wrong-data-type edge case: every numeric operator must reject
    non-numeric input with a clear ConfigurationError, never a bare
    TypeError, and must specifically reject booleans (since bool is a
    subclass of int in Python and could silently coerce to 0/1)."""

    def test_string_value_raises(self):
        with pytest.raises(ConfigurationError):
            OPERATORS["gt"]("not_a_number", {"value": 30}, {})

    def test_none_value_in_comparison_raises(self):
        # Note: in normal engine use, a None actual_value never reaches
        # an operator (callers filter it out beforehand) -- this test
        # documents the operator's own defensive behavior if it ever did.
        with pytest.raises(ConfigurationError):
            OPERATORS["gt"](None, {"value": 30}, {})

    def test_boolean_value_raises(self):
        with pytest.raises(ConfigurationError):
            OPERATORS["gt"](True, {"value": 0}, {})

    def test_boolean_threshold_raises(self):
        with pytest.raises(ConfigurationError):
            OPERATORS["gt"](5, {"value": True}, {})


class TestOperatorRegistry:
    def test_get_operator_returns_callable(self):
        func = get_operator("gt")
        assert callable(func)

    def test_get_unknown_operator_raises_specific_error(self):
        with pytest.raises(OperatorNotSupportedError):
            get_operator("frobnicate")

    def test_register_new_operator_at_runtime(self):
        def _always_true(actual, rule, profile):
            return True

        register_operator("always_true_test_op", _always_true)
        try:
            func = get_operator("always_true_test_op")
            assert func(123, {}, {}) is True
        finally:
            del OPERATORS["always_true_test_op"]  # don't leak into other tests
