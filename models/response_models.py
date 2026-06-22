"""
Typed models for engine output -- gap analysis and eligibility results.

Kept separate from rule_models.py since these represent the *output*
shape (what main.py serializes to JSON), not the *configuration* shape.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GapResult:
    id: str
    impact: str
    estimated_score_gain: int
    current_value: Any = None
    action: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GapAnalysisResult:
    customer_id: str | None
    gaps_found: int
    total_potential_score_gain: int
    gaps: list[GapResult]

    def to_dict(self) -> dict:
        return {
            "mode": "gap_analysis",
            "customer_id": self.customer_id,
            "gaps_found": self.gaps_found,
            "total_potential_score_gain": self.total_potential_score_gain,
            "gaps": [g.to_dict() for g in self.gaps],
        }


@dataclass(frozen=True)
class RuleEvaluationResult:
    rule: str
    passed: bool
    reason: str | None = None

    def to_dict(self) -> dict:
        d = {"rule": self.rule, "passed": self.passed}
        if self.reason is not None:
            d["reason"] = self.reason
        return d


@dataclass(frozen=True)
class EligibilityResult:
    customer_id: str | None
    eligible: bool
    rules: list[RuleEvaluationResult]
    fail_reasons: list[str]
    next_step: str | None = None
    risk_score: float | None = None  # bonus: weighted risk score

    def to_dict(self) -> dict:
        d = {
            "mode": "eligibility",
            "customer_id": self.customer_id,
            "eligible": self.eligible,
            "rules": [r.to_dict() for r in self.rules],
            "fail_reasons": self.fail_reasons,
        }
        if self.next_step is not None:
            d["next_step"] = self.next_step
        if self.risk_score is not None:
            d["risk_score"] = round(self.risk_score, 2)
        return d
