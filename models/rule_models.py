"""
Typed models for parsed rule configuration.

These are deliberately plain dataclasses (not Pydantic) -- the rules
come from a YAML file we control the schema of and validate explicitly
in rule_loader.py, so a heavier validation library doesn't earn its
complexity here the way it does for an HTTP request boundary.

EligibilityRuleGroup.logic is typed as a Literal["AND", "OR"] today even
though the sample config only uses AND -- this is the "future-ready for
OR" requirement: the data model already supports OR, and evaluator.py's
group-evaluation function already branches on this field (see
engine/evaluator.py), so introducing OR groups in rules.yaml requires
zero code changes, only a YAML edit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class GapRule:
    id: str
    field: str
    operator: str
    impact: Literal["high", "medium", "low"]
    estimated_score_gain: int
    action_template: str
    # Operator-specific extra keys (value, min, max, values, etc.) are
    # kept as a raw dict rather than being broken out into named fields,
    # since different operators need different extra keys and forcing
    # them all into the dataclass would mean most fields are None for
    # most operators. The operator functions in operators.py read
    # directly from this dict.
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EligibilitySubRule:
    id: str
    field: str
    operator: str
    message: str
    weight: float = 1.0  # used only by the bonus weighted risk-score feature
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EligibilityRuleGroup:
    name: str
    logic: Literal["AND", "OR"]
    rules: list[EligibilitySubRule]


@dataclass(frozen=True)
class RuleSet:
    """The fully parsed, validated contents of rules.yaml."""

    gap_rules: list[GapRule]
    eligibility_rules: list[EligibilityRuleGroup]
