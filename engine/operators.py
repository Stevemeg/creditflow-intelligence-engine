"""
Operator registry: the heart of the engine's extensibility story.

Every comparison the engine can perform is a small, pure function with
the signature:

    (actual_value, rule: dict, profile: dict) -> bool

registered in OPERATORS under its YAML name. Evaluating a rule never
branches on operator name via if/elif -- it looks the function up in
this dict and calls it. Adding a new operator means writing one function
and adding one registry entry; nothing else in the engine changes.

`profile` is passed to every operator (not just lte_multiplier) so that
*any* future operator can reference other fields on the same record
without changing the registry's calling convention.

Every operator treats `None` (missing/null field) as "cannot evaluate,
not true" rather than raising -- the missing-field case is surfaced
once, clearly, by the caller (rule_loader/evaluator) before any operator
is invoked, so operators themselves can assume `actual_value` is present
and just need to guard against type mismatches.
"""
from __future__ import annotations

from typing import Any, Callable

from engine.exceptions import ConfigurationError, OperatorNotSupportedError

OperatorFunc = Callable[[Any, dict, dict], bool]


def _op_gt(actual: Any, rule: dict, profile: dict) -> bool:
    return _coerce_numeric(actual) > _coerce_numeric(rule["value"])


def _op_gte(actual: Any, rule: dict, profile: dict) -> bool:
    return _coerce_numeric(actual) >= _coerce_numeric(rule["value"])


def _op_lt(actual: Any, rule: dict, profile: dict) -> bool:
    return _coerce_numeric(actual) < _coerce_numeric(rule["value"])


def _op_lte(actual: Any, rule: dict, profile: dict) -> bool:
    return _coerce_numeric(actual) <= _coerce_numeric(rule["value"])


def _op_eq(actual: Any, rule: dict, profile: dict) -> bool:
    return _strict_equals(actual, rule["value"])


def _op_neq(actual: Any, rule: dict, profile: dict) -> bool:
    return not _strict_equals(actual, rule["value"])


def _strict_equals(a: Any, b: Any) -> bool:
    """Plain `==` with one deliberate carve-out: Python treats bool as a
    subclass of int, so `False == 0` and `True == 1` are both True by
    default. That's almost never the intent for a rules-engine equality
    check (e.g. a malformed `written_off_accounts: true` should not
    silently satisfy `written_off_accounts == 0`), so a bool on either
    side that doesn't match a bool on the other side is never equal,
    regardless of numeric value."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def _op_between(actual: Any, rule: dict, profile: dict) -> bool:
    value = _coerce_numeric(actual)
    lo, hi = rule.get("min"), rule.get("max")
    if lo is None or hi is None:
        raise ConfigurationError(
            f"'between' operator on rule '{rule.get('id')}' requires both "
            "'min' and 'max' keys."
        )
    return _coerce_numeric(lo) <= value <= _coerce_numeric(hi)


def _op_in(actual: Any, rule: dict, profile: dict) -> bool:
    values = rule.get("values")
    if values is None:
        raise ConfigurationError(
            f"'in' operator on rule '{rule.get('id')}' requires a 'values' list."
        )
    return actual in values


def _op_not_in(actual: Any, rule: dict, profile: dict) -> bool:
    values = rule.get("values")
    if values is None:
        raise ConfigurationError(
            f"'not_in' operator on rule '{rule.get('id')}' requires a 'values' list."
        )
    return actual not in values


def _op_lte_multiplier(actual: Any, rule: dict, profile: dict) -> bool:
    multiplier_field = rule.get("multiplier_field")
    multiplier = rule.get("multiplier")
    if multiplier_field is None or multiplier is None:
        raise ConfigurationError(
            f"'lte_multiplier' operator on rule '{rule.get('id')}' requires "
            "both 'multiplier_field' and 'multiplier' keys."
        )
    other_value = profile.get(multiplier_field)
    if other_value is None:
        # The field this rule multiplies against is itself missing from
        # the input -- this is a data problem, not a config problem, so
        # it's surfaced as "rule cannot be evaluated" by the caller
        # rather than raised here (consistent with how a missing
        # `actual` value is handled).
        raise ConfigurationError(
            f"lte_multiplier rule '{rule.get('id')}' references missing "
            f"field '{multiplier_field}' in the input data."
        )
    return _coerce_numeric(actual) <= _coerce_numeric(other_value) * _coerce_numeric(multiplier)


def _coerce_numeric(value: Any) -> float:
    """Centralised numeric coercion so every comparison operator rejects
    non-numeric input the same way, with a clear error rather than a
    confusing TypeError deep in a comparison."""
    if isinstance(value, bool):
        # bool is a subclass of int in Python; silently treating True/False
        # as 1/0 in a numeric threshold comparison would be a real bug
        # (e.g. comparing a boolean "has_defaulted" field against a score
        # threshold should never accidentally succeed).
        raise ConfigurationError(f"Expected a numeric value, got boolean: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ConfigurationError(f"Expected a numeric value, got: {value!r}")


OPERATORS: dict[str, OperatorFunc] = {
    "gt": _op_gt,
    "gte": _op_gte,
    "lt": _op_lt,
    "lte": _op_lte,
    "eq": _op_eq,
    "neq": _op_neq,
    "between": _op_between,
    "in": _op_in,
    "not_in": _op_not_in,
    "lte_multiplier": _op_lte_multiplier,
}


def get_operator(name: str) -> OperatorFunc:
    """Look up an operator by name, raising a clear, specific error if
    it isn't registered -- this is the single chokepoint that makes
    'unknown operator' a fail-fast, well-typed error everywhere in the
    engine instead of a KeyError surfacing from deep inside evaluation."""
    try:
        return OPERATORS[name]
    except KeyError:
        raise OperatorNotSupportedError(
            f"Operator '{name}' is not supported. "
            f"Supported operators: {sorted(OPERATORS.keys())}"
        )


def register_operator(name: str, func: OperatorFunc) -> None:
    """Register a new operator at runtime. Exists so the registry can be
    extended without editing this file at all if desired (e.g. from a
    plugin or a test), though for built-in operators editing this file
    directly is equally valid -- both paths converge on the same dict."""
    OPERATORS[name] = func
