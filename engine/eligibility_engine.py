"""
Eligibility Mode: given a customer profile, evaluate loan eligibility
against every configured rule and return pass/fail + a reason for each.

Group logic (AND/OR):
A customer is eligible only if EVERY group's logic is satisfied.
Within a group:
    AND -> every sub-rule in the group must pass
    OR  -> at least one sub-rule in the group must pass
The sample config only uses one AND group, but this function already
branches on `group.logic`, so adding an OR group to rules.yaml requires
no code change -- this is the "future-ready for OR" requirement.

Every individual sub-rule's pass/fail and message is reported regardless
of group logic or short-circuiting, since the brief requires detailed
reasoning per rule, not just an aggregate pass/fail.
"""
from __future__ import annotations

from engine.exceptions import ConfigurationError
from engine.operators import get_operator
from models.response_models import EligibilityResult, RuleEvaluationResult
from models.rule_models import EligibilitySubRule, RuleSet


def evaluate_eligibility(
    rule_set: RuleSet, customer_profile: dict, include_risk_score: bool = True
) -> EligibilityResult:
    if not isinstance(customer_profile, dict):
        raise ConfigurationError("customer_profile must be a JSON object (dict).")

    all_results: list[RuleEvaluationResult] = []
    group_outcomes: list[bool] = []
    failed_ids: list[str] = []
    total_weight = 0.0
    failed_weight = 0.0

    for group in rule_set.eligibility_rules:
        sub_results = [_evaluate_subrule(sub, customer_profile) for sub in group.rules]
        all_results.extend(sub_results)

        for sub, result in zip(group.rules, sub_results):
            total_weight += sub.weight
            if not result.passed:
                failed_ids.append(sub.id)
                failed_weight += sub.weight

        passed_flags = [r.passed for r in sub_results]
        group_passed = all(passed_flags) if group.logic == "AND" else any(passed_flags)
        group_outcomes.append(group_passed)

    eligible = all(group_outcomes) if group_outcomes else True

    risk_score = None
    if include_risk_score and total_weight > 0:
        risk_score = (failed_weight / total_weight) * 100

    next_step = None if eligible else _build_next_step(failed_ids, all_results)

    return EligibilityResult(
        customer_id=customer_profile.get("customer_id"),
        eligible=eligible,
        rules=all_results,
        fail_reasons=failed_ids,
        next_step=next_step,
        risk_score=risk_score,
    )


def _evaluate_subrule(sub: EligibilitySubRule, customer_profile: dict) -> RuleEvaluationResult:
    actual_value = customer_profile.get(sub.field)
    if actual_value is None:
        return RuleEvaluationResult(
            rule=sub.id,
            passed=False,
            reason=f"Required field '{sub.field}' is missing from the customer profile.",
        )

    operator_func = get_operator(sub.operator)
    rule_dict = {"id": sub.id, **sub.extra}
    try:
        passed = operator_func(actual_value, rule_dict, customer_profile)
    except ConfigurationError as exc:
        return RuleEvaluationResult(
            rule=sub.id,
            passed=False,
            reason=f"Could not evaluate rule: {exc}",
        )

    return RuleEvaluationResult(rule=sub.id, passed=passed, reason=None if passed else sub.message)


def _build_next_step(failed_ids: list[str], all_results: list[RuleEvaluationResult]) -> str:
    """A short, human-readable hint at what to fix first. Points at the
    first failed rule's message, since that's almost always the most
    actionable single piece of feedback -- if there's a credit-score
    failure specifically, that's surfaced first since it's resolvable
    via the gap-analysis half of the system.

    Only called when `eligible` is False, at which point `failed_ids` is
    guaranteed non-empty by construction (a group can only fail if at
    least one of its sub-rules failed, for both AND and OR semantics).
    The `if not failed_ids` guard below is unreachable in practice; it
    exists purely as a defensive fallback should that invariant ever
    change, not because it represents a real code path today.
    """
    if "cibil_score" in failed_ids:
        return "Improve CIBIL score. See gap analysis for specific improvement actions."
    if not failed_ids:  # pragma: no cover -- see docstring; defensive only
        return ""
    first_failure = next(r for r in all_results if r.rule == failed_ids[0])
    return first_failure.reason or "Review the failed eligibility rules above."
