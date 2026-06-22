"""
Custom exception hierarchy for the rule engine.

Every failure mode in this system raises one of these rather than a bare
built-in exception, so callers (and the HTTP layer, if used) can branch
on exception type instead of parsing error strings.

RuleEngineError
├── RuleLoadError            -- rules.yaml is malformed or fails schema validation
│   └── ConfigurationError   -- a structurally-valid rule references something invalid
│       (unknown operator, duplicate id, missing required key, etc.)
├── OperatorNotSupportedError -- a rule references an operator with no
│                                registered implementation
└── ValidationError           -- the *input data* (credit report / customer
                                  profile) is invalid, not the rule config
"""


class RuleEngineError(Exception):
    """Base class for all rule-engine errors."""


class RuleLoadError(RuleEngineError):
    """Raised when rules.yaml cannot be parsed or fails schema validation
    (malformed YAML, missing required top-level keys, duplicate rule ids,
    invalid impact values, invalid rule structures)."""


class ConfigurationError(RuleLoadError):
    """Raised when a rule is structurally valid YAML but semantically
    invalid -- e.g. an eligibility rule with operator 'lte_multiplier'
    that doesn't specify a multiplier_field, or a duplicate rule id."""


class OperatorNotSupportedError(RuleEngineError):
    """Raised when a rule references an operator with no registered
    implementation in the operator registry."""


class ValidationError(RuleEngineError):
    """Raised when the *input data* being evaluated (a credit report or
    customer profile) is invalid -- not valid JSON, missing required
    fields the rules need, or fields of the wrong type."""
