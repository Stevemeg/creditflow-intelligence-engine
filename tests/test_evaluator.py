"""
Tests for evaluator.py: the RuleEngine façade that main.py and the
bonus HTTP endpoint both depend on. Verifies it loads rules once,
dispatches both modes correctly, and raises a clear error for an
unknown mode.
"""
import json
from pathlib import Path

import pytest

from engine.evaluator import RuleEngine
from engine.exceptions import ConfigurationError, RuleEngineError, RuleLoadError

RULES_PATH = Path(__file__).parent.parent / "rules.yaml"
CREDIT_REPORT_PATH = Path(__file__).parent.parent / "sample_data" / "credit_report.json"
CUSTOMER_PROFILE_PATH = Path(__file__).parent.parent / "sample_data" / "customer_profile.json"


@pytest.fixture(scope="module")
def engine():
    return RuleEngine(RULES_PATH)


class TestRuleEngineConstruction:
    def test_loads_rules_successfully(self, engine):
        assert len(engine.rule_set.gap_rules) == 5
        assert len(engine.rule_set.eligibility_rules) == 1

    def test_invalid_rules_path_raises_at_construction(self):
        with pytest.raises(RuleLoadError):
            RuleEngine("nonexistent_rules_file.yaml")


class TestRuleEngineRunDispatch:
    def test_gap_analysis_mode(self, engine):
        with open(CREDIT_REPORT_PATH) as f:
            report = json.load(f)
        result = engine.run("gap_analysis", report)
        assert result["mode"] == "gap_analysis"
        assert result["gaps_found"] == 3

    def test_eligibility_mode(self, engine):
        with open(CUSTOMER_PROFILE_PATH) as f:
            profile = json.load(f)
        result = engine.run("eligibility", profile)
        assert result["mode"] == "eligibility"
        assert result["eligible"] is False

    def test_unknown_mode_raises_configuration_error(self, engine):
        with pytest.raises(ConfigurationError, match="Unknown mode"):
            engine.run("not_a_real_mode", {})

    def test_result_is_json_serializable(self, engine):
        with open(CREDIT_REPORT_PATH) as f:
            report = json.load(f)
        result = engine.run("gap_analysis", report)
        # Must not raise -- proves every field in the output is a plain
        # JSON-compatible type (no stray dataclass/Enum instances leaking
        # through to_dict()).
        json.dumps(result)


class TestRuleEngineErrorIsImportableAsBaseClass:
    def test_rule_engine_error_exported(self):
        # main.py and any future HTTP layer catch RuleEngineError as the
        # single base class for all engine failures -- confirm it's
        # actually exported from evaluator.py's public surface.
        from engine.evaluator import RuleEngineError as ImportedFromEvaluator

        assert ImportedFromEvaluator is RuleEngineError
