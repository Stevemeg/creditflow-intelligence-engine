"""
Bonus feature: expose both engine modes via a single HTTP endpoint.

    POST /analyse
    Content-Type: application/json

    { "mode": "gap_analysis", "customer_id": "C001", "credit_utilisation_pct": 87, ... }

The request body is the credit report or customer profile with one
extra top-level key, `mode`, telling the engine which evaluation to run.
Everything else in the body is passed straight through as the payload --
this mirrors the brief's example exactly (mode + customer_id + data
fields all flat in one object, not nested).

This module is intentionally separate from engine/evaluator.py: the
engine itself has zero HTTP dependencies and can be used as a pure
library (as main.py does) without ever importing FastAPI. Only this
file -- the optional bonus layer -- depends on the web framework.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from engine.evaluator import RuleEngine
from engine.exceptions import RuleEngineError

RULES_PATH = "rules.yaml"

_engine: RuleEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine
    # Load and validate rules.yaml exactly once at startup -- a bad
    # config fails the server's boot, not the first request.
    _engine = RuleEngine(RULES_PATH)
    yield


app = FastAPI(
    title="Softlend Credit Gap Analyser & Loan Eligibility Evaluator",
    description="Exposes gap_analysis and eligibility modes via a single /analyse endpoint.",
    version="1.0.0",
    lifespan=lifespan,
)


class AnalyseRequest(BaseModel):
    """Deliberately permissive: `mode` is the only field this API cares
    about by name. Every other field (customer_id, credit_utilisation_pct,
    cibil_score, etc.) varies by mode and is passed through untouched, so
    this schema doesn't need to know the full field list for either mode --
    that knowledge already lives in rules.yaml, which is the whole point
    of a config-driven engine."""

    mode: str

    model_config = ConfigDict(extra="allow")


@app.exception_handler(RuleEngineError)
def handle_rule_engine_error(request: Request, exc: RuleEngineError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": str(exc), "code": type(exc).__name__},
    )


@app.post("/analyse")
def analyse(payload: AnalyseRequest) -> dict[str, Any]:
    body = payload.model_dump()
    mode = body.pop("mode")
    return _engine.run(mode, body)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
