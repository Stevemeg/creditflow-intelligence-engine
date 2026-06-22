"""
Loads and validates rules.yaml into a typed RuleSet.

Validation happens entirely here, at load time, not during evaluation --
this is the "fail fast" requirement: a malformed or semantically invalid
rules.yaml is rejected the moment the engine starts, with a specific,
actionable error, rather than surfacing as a confusing failure on the
first request that happens to trigger the bad rule.

Validation performed (in order):
1. The YAML itself must parse (malformed YAML -> RuleLoadError)
2. Top-level structure must have 'gap_rules' and 'eligibility_rules' keys
3. Every gap rule must have all required keys, a valid impact value, a
   positive estimated_score_gain, and a registered operator
4. Every eligibility rule must have all required keys and a registered
   operator
5. No duplicate rule ids, anywhere -- across both gap rules and
   eligibility sub-rules, since ids are meant to be referenceable
   identifiers and a duplicate silently shadows the first definition
"""
from __future__ import annotations

from pathlib import Path

import yaml

from engine.exceptions import ConfigurationError, RuleLoadError
from engine.operators import get_operator
from models.rule_models import EligibilityRuleGroup, EligibilitySubRule, GapRule, RuleSet

VALID_IMPACTS = {"high", "medium", "low"}
VALID_GROUP_LOGIC = {"AND", "OR"}

# Keys consumed into named dataclass fields; everything else on a gap
# rule dict is operator-specific config and goes into GapRule.extra.
_GAP_RULE_NAMED_KEYS = {"id", "field", "operator", "impact", "estimated_score_gain", "action_template"}
_ELIGIBILITY_SUBRULE_NAMED_KEYS = {"id", "field", "operator", "message", "weight"}


def load_rules(path: str | Path) -> RuleSet:
    """Load and fully validate rules.yaml. Raises RuleLoadError (or its
    subclass ConfigurationError) on any structural or semantic problem;
    never returns a partially-valid RuleSet."""
    path = Path(path)
    if not path.exists():
        raise RuleLoadError(f"Rules file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except OSError as exc:
        raise RuleLoadError(f"Could not read rules file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise RuleLoadError(f"Malformed YAML in {path}: {exc}") from exc

    if raw is None:
        raise RuleLoadError(f"Rules file {path} is empty.")
    if not isinstance(raw, dict):
        raise RuleLoadError(f"Rules file {path} must define a YAML mapping at the top level.")

    gap_rules = _parse_gap_rules(raw.get("gap_rules", []))
    eligibility_groups = _parse_eligibility_groups(raw.get("eligibility_rules", []))

    _check_no_duplicate_ids(gap_rules, eligibility_groups)

    return RuleSet(gap_rules=gap_rules, eligibility_rules=eligibility_groups)


def _parse_gap_rules(raw_rules: object) -> list[GapRule]:
    if not isinstance(raw_rules, list):
        raise RuleLoadError("'gap_rules' must be a list.")

    parsed: list[GapRule] = []
    for i, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise ConfigurationError(f"gap_rules[{i}] must be a mapping, got {type(raw).__name__}.")

        missing = _GAP_RULE_NAMED_KEYS - raw.keys()
        if missing:
            raise ConfigurationError(
                f"gap_rules[{i}] (id={raw.get('id', '?')!r}) is missing required keys: {sorted(missing)}"
            )

        impact = raw["impact"]
        if impact not in VALID_IMPACTS:
            raise ConfigurationError(
                f"gap_rules[{i}] (id={raw['id']!r}) has invalid impact {impact!r}; "
                f"must be one of {sorted(VALID_IMPACTS)}."
            )

        gain = raw["estimated_score_gain"]
        if not isinstance(gain, int) or isinstance(gain, bool) or gain <= 0:
            raise ConfigurationError(
                f"gap_rules[{i}] (id={raw['id']!r}) has invalid estimated_score_gain "
                f"{gain!r}; must be a positive integer."
            )

        # Fail fast on an unknown operator at LOAD time, not at first use.
        get_operator(raw["operator"])

        extra = {k: v for k, v in raw.items() if k not in _GAP_RULE_NAMED_KEYS}
        parsed.append(
            GapRule(
                id=raw["id"],
                field=raw["field"],
                operator=raw["operator"],
                impact=impact,
                estimated_score_gain=gain,
                action_template=raw["action_template"],
                extra=extra,
            )
        )
    return parsed


def _parse_eligibility_groups(raw_groups: object) -> list[EligibilityRuleGroup]:
    if not isinstance(raw_groups, list):
        raise RuleLoadError("'eligibility_rules' must be a list.")

    parsed: list[EligibilityRuleGroup] = []
    for gi, raw_group in enumerate(raw_groups):
        if not isinstance(raw_group, dict):
            raise ConfigurationError(
                f"eligibility_rules[{gi}] must be a mapping, got {type(raw_group).__name__}."
            )

        for key in ("name", "logic", "rules"):
            if key not in raw_group:
                raise ConfigurationError(f"eligibility_rules[{gi}] is missing required key '{key}'.")

        logic = raw_group["logic"]
        if logic not in VALID_GROUP_LOGIC:
            raise ConfigurationError(
                f"eligibility_rules[{gi}] (name={raw_group['name']!r}) has invalid logic "
                f"{logic!r}; must be one of {sorted(VALID_GROUP_LOGIC)}."
            )

        raw_subrules = raw_group["rules"]
        if not isinstance(raw_subrules, list) or not raw_subrules:
            raise ConfigurationError(
                f"eligibility_rules[{gi}] (name={raw_group['name']!r}) must have a "
                "non-empty 'rules' list."
            )

        subrules = [_parse_eligibility_subrule(raw_group["name"], i, r) for i, r in enumerate(raw_subrules)]
        parsed.append(EligibilityRuleGroup(name=raw_group["name"], logic=logic, rules=subrules))
    return parsed


def _parse_eligibility_subrule(group_name: str, index: int, raw: object) -> EligibilitySubRule:
    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"eligibility_rules[{group_name}].rules[{index}] must be a mapping, "
            f"got {type(raw).__name__}."
        )

    missing = {"id", "field", "operator", "message"} - raw.keys()
    if missing:
        raise ConfigurationError(
            f"eligibility_rules[{group_name}].rules[{index}] (id={raw.get('id', '?')!r}) "
            f"is missing required keys: {sorted(missing)}"
        )

    # Fail fast on an unknown operator at LOAD time, not at first use.
    get_operator(raw["operator"])

    weight = raw.get("weight", 1.0)
    if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight < 0:
        raise ConfigurationError(
            f"eligibility rule '{raw['id']}' has invalid weight {weight!r}; "
            "must be a non-negative number."
        )

    extra = {k: v for k, v in raw.items() if k not in _ELIGIBILITY_SUBRULE_NAMED_KEYS}
    return EligibilitySubRule(
        id=raw["id"],
        field=raw["field"],
        operator=raw["operator"],
        message=raw["message"],
        weight=float(weight),
        extra=extra,
    )


def _check_no_duplicate_ids(
    gap_rules: list[GapRule], eligibility_groups: list[EligibilityRuleGroup]
) -> None:
    seen: dict[str, str] = {}  # id -> where it was first seen, for a helpful error message

    def _check(rule_id: str, location: str) -> None:
        if rule_id in seen:
            raise ConfigurationError(
                f"Duplicate rule id '{rule_id}' found in both {seen[rule_id]} and {location}. "
                "Rule ids must be unique across the entire rules.yaml file."
            )
        seen[rule_id] = location

    for gr in gap_rules:
        _check(gr.id, f"gap_rules (id={gr.id})")

    for group in eligibility_groups:
        for sub in group.rules:
            _check(sub.id, f"eligibility_rules[{group.name}] (id={sub.id})")
