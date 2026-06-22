"""
Tests for the bonus HTTP endpoint (api.py). Uses FastAPI's TestClient
so no real server process is needed; the lifespan hook still runs,
loading the real rules.yaml exactly as it would in production.
"""
import pytest
from fastapi.testclient import TestClient

from api import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_analyse_gap_analysis_mode(client):
    resp = client.post(
        "/analyse",
        json={
            "mode": "gap_analysis",
            "customer_id": "C001",
            "credit_utilisation_pct": 87,
            "missed_payments_12m": 2,
            "written_off_accounts": 0,
            "credit_age_months": 14,
            "hard_enquiries_6m": 2,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "gap_analysis"
    assert body["gaps_found"] == 3
    assert body["total_potential_score_gain"] == 70


def test_analyse_eligibility_mode(client):
    resp = client.post(
        "/analyse",
        json={
            "mode": "eligibility",
            "customer_id": "C001",
            "age": 29,
            "cibil_score": 620,
            "monthly_income": 60000,
            "existing_emis": 15000,
            "foir": 0.25,
            "employment_type": "salaried",
            "written_off_accounts": 0,
            "requested_amount": 400000,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "eligibility"
    assert body["eligible"] is False
    assert body["fail_reasons"] == ["cibil_score"]


def test_analyse_unknown_mode_returns_400(client):
    resp = client.post("/analyse", json={"mode": "bogus_mode"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "ConfigurationError"


def test_analyse_missing_mode_returns_422(client):
    # `mode` has no default, so FastAPI's own request validation
    # rejects this before it ever reaches the engine.
    resp = client.post("/analyse", json={"customer_id": "C001"})
    assert resp.status_code == 422
