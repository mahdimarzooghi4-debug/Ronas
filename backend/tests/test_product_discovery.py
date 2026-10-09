"""Contract and boundary tests for the non-operational foundation."""

from fastapi.testclient import TestClient
import pytest

from ronas.app import app
from ronas.catalog import DOMESTIC, ENGINES, EXPORT, find_engine

client = TestClient(app)


def test_health_is_liveness_only() -> None:
    assert client.get("/healthz").json() == {
        "status": "alive",
        "scope": "design_only",
    }


def test_exactly_two_independent_engines_with_open_business_gates() -> None:
    result = client.get("/api/v1/product/engines")
    assert result.status_code == 200
    body = result.json()
    assert {engine["key"] for engine in body} == {"domestic", "export"}
    assert {engine["business_gate"] for engine in body} == {"OPEN"}
    assert {engine["capability_count"] for engine in body} == {10, 9}
    assert not any("production_ready" in entry for entry in body)


@pytest.mark.parametrize(
    ("engine_key", "prefix", "count", "source"),
    [
        ("domestic", "D-", 10, "docs/business/01-domestic-engine.md"),
        ("export", "E-", 9, "docs/business/02-export-engine.md"),
    ],
)
def test_capability_lineage_is_engine_isolated(
    engine_key: str, prefix: str, count: int, source: str
) -> None:
    response = client.get(f"/api/v1/product/engines/{engine_key}/capabilities")
    assert response.status_code == 200
    capabilities = response.json()
    assert len(capabilities) == count
    assert {cap["code"] for cap in capabilities} == {
        f"{prefix}{i:02d}" for i in range(1, count + 1)
    }
    assert all(cap["code"].startswith(prefix) for cap in capabilities)
    assert all(cap["source_ref"] == source for cap in capabilities)
    assert all(cap["status"] == "DESIGN_ONLY" for cap in capabilities)


def test_engine_detail_matches_corresponding_manifest() -> None:
    for key in ("domestic", "export"):
        detail = client.get(f"/api/v1/product/engines/{key}")
        assert detail.status_code == 200
        data = detail.json()
        assert data["key"] == key
        assert data["business_gate"] == "OPEN"
        assert len(data["capabilities"]) == data["capability_count"]


def test_unknown_engine_is_rejected_without_fallback() -> None:
    assert find_engine("international") is None
    for path in (
        "/api/v1/product/engines/international",
        "/api/v1/product/engines/international/capabilities",
        "/api/v1/product/engines/DOMESTIC",
    ):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["detail"] == "Unknown engine"


def test_mutating_verbs_not_implemented() -> None:
    for path in (
        "/api/v1/product/engines",
        "/api/v1/product/engines/domestic",
        "/api/v1/product/engines/export/capabilities",
    ):
        assert client.post(path, json={}).status_code == 405
        assert client.patch(path, json={}).status_code == 405
        assert client.delete(path).status_code == 405


def test_only_get_routes_are_published_under_api_prefix() -> None:
    api_routes = [
        route for route in app.routes if route.path.startswith("/api/v1/")
    ]
    assert len(api_routes) == 3
    assert all(route.methods == {"GET"} for route in api_routes)


def test_no_operational_or_sensitive_data_is_exposed() -> None:
    response = client.get("/api/v1/product/engines/export")
    assert response.status_code == 200
    raw = response.text.lower()
    for field in (
        "commission",
        "bank_account",
        "settlement",
        "exchange_rate",
        "secret",
        "api_key",
        "owner_id",
        "personal",
    ):
        assert f'"{field}"' not in raw


def test_registry_is_immutable_and_contains_no_cross_engine_records() -> None:
    assert len(ENGINES) == 2
    assert find_engine("domestic") is DOMESTIC
    assert find_engine("export") is EXPORT
    assert not set(DOMESTIC.capabilities).intersection(EXPORT.capabilities)
    with pytest.raises(AttributeError):
        DOMESTIC.business_gate = "APPROVED"  # type: ignore[misc]
