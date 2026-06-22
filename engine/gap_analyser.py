"""
Gap Analysis Mode: given a credit report, determine which gap rules
fire and produce a ranked list of improvement actions.

Sorting (explicitly required, and tested in test_gap_analysis.py):
    1. impact: high -> medium -> low
    2. within the same impact: estimated_score_gain descending
"""
from __future__ import annotations

from engine.exceptions import ConfigurationError
from engine.operators import get_operator
from models.response_models import GapAnalysisResult, GapResult
from models.rule_models import GapRule, RuleSet

_IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}


def analyse_gaps(rule_set: RuleSet, credit_report: dict) -> GapAnalysisResult:
    if not isinstance(credit_report, dict):
        raise ConfigurationError("credit_report must be a JSON object (dict).")

    fired: list[GapResult] = []
    for rule in rule_set.gap_rules:
        result = _evaluate_gap_rule(rule, credit_report)
        if result is not None:
            fired.append(result)

    fired.sort(key=lambda g: (_IMPACT_ORDER[g.impact], -g.estimated_score_gain))

    total_gain = sum(g.estimated_score_gain for g in fired)

    return GapAnalysisResult(
        customer_id=credit_report.get("customer_id"),
        gaps_found=len(fired),
        total_potential_score_gain=total_gain,
        gaps=fired,
    )


def _evaluate_gap_rule(rule: GapRule, credit_report: dict) -> GapResult | None:
    """Returns a GapResult if the rule fires, or None if it doesn't fire
    or can't be evaluated (field missing/null in the input -- a missing
    field is treated as "rule does not fire" rather than an error, since
    a credit report legitimately may not report every possible factor)."""
    actual_value = credit_report.get(rule.field)
    if actual_value is None:
        return None

    operator_func = get_operator(rule.operator)
    try:
        fired = operator_func(actual_value, _gap_rule_as_dict(rule), credit_report)
    except ConfigurationError:
        # An operator-level config problem (e.g. a non-numeric value
        # where a number was expected) means this specific rule can't be
        # evaluated against this input -- treat as "doesn't fire" rather
        # than aborting the entire analysis over one bad rule/field
        # combination.
        return None

    if not fired:
        return None

    action = _render_action_template(rule.action_template, actual_value, credit_report, rule.field)
    return GapResult(
        id=rule.id,
        impact=rule.impact,
        estimated_score_gain=rule.estimated_score_gain,
        current_value=actual_value,
        action=action,
    )


def _gap_rule_as_dict(rule: GapRule) -> dict:
    """Operators expect a plain dict (id, value/min/max/etc.) -- this
    merges the rule's named fields with its operator-specific `extra`
    dict into the shape operators.py expects."""
    return {"id": rule.id, **rule.extra}


def _render_action_template(template: str, current_value, full_record: dict, field_name: str) -> str:
    """Substitutes {current_value} and any other {field_name} present in
    full_record into the action_template string. Missing template
    variables are left as-is rather than raising, so a typo in a
    template doesn't take down the whole analysis -- it just produces a
    slightly malformed (but still informative) action string, which is
    easy to spot and fix in rules.yaml.
    """
    context = dict(full_record)
    context["current_value"] = current_value
    try:
        return template.format(**context)
    except (KeyError, IndexError):
        # A {placeholder} in the template has no matching key in the
        # input record. Fall back to substituting only what we can,
        # leaving unmatched placeholders literally in the string.
        return _safe_format(template, context)
    except ValueError:
        # The template itself is malformed (e.g. an unclosed brace, or
        # invalid format-spec syntax like "{current_value:zz}"). This is
        # a config-authoring mistake in rules.yaml, not a data problem --
        # per the fail-safe requirement, this must never crash the whole
        # analysis. Returning the raw, unrendered template string is the
        # most honest fallback: it's visibly wrong (easy for whoever
        # edited rules.yaml to spot and fix) rather than silently
        # swallowed or guessed at.
        return template


def _safe_format(template: str, context: dict) -> str:
    class _SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return template.format_map(_SafeDict(context))
    except ValueError:
        # Same malformed-syntax case as above, reached via the
        # KeyError/IndexError fallback path instead of the primary one.
        return template
