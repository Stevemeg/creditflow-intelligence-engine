"""
Single orchestration entry point for the engine.

This is the one module both main.py (CLI) and the bonus HTTP endpoint
import -- neither needs to know about rule_loader/gap_analyser/
eligibility_engine individually, which keeps those three modules free to
change independently as long as this thin façade's signature is stable.
"""
from __future__ import annotations

from pathlib import Path

from engine.eligibility_engine import evaluate_eligibility
from engine.exceptions import ConfigurationError, RuleEngineError
from engine.gap_analyser import analyse_gaps
from engine.rule_loader import load_rules
from models.rule_models import RuleSet


class RuleEngine:
    """Loads rules.yaml once and exposes both evaluation modes. Loading
    is intentionally separated from evaluation (constructor vs. methods)
    so a long-running process -- e.g. the HTTP server -- pays the
    YAML-parsing and validation cost exactly once at startup, not on
    every request."""

    def __init__(self, rules_path: str | Path = "rules.yaml"):
        self.rule_set: RuleSet = load_rules(rules_path)

    def run(self, mode: str, payload: dict) -> dict:
        """Dispatch to the correct mode and return a plain dict, ready
        for json.dumps. Raises RuleEngineError (or a subclass) for any
        failure -- callers decide how to present that (CLI exits
        non-zero with a message; the HTTP layer returns a 4xx)."""
        if mode == "gap_analysis":
            return analyse_gaps(self.rule_set, payload).to_dict()
        if mode == "eligibility":
            return evaluate_eligibility(self.rule_set, payload).to_dict()
        raise ConfigurationError(
            f"Unknown mode '{mode}'. Supported modes: 'gap_analysis', 'eligibility'."
        )


__all__ = ["RuleEngine", "RuleEngineError"]
