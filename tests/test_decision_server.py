from __future__ import annotations

import json
from pathlib import Path

import pytest

from acce_optimizer.core.errors import ContractValidationError
from acce_optimizer.core.decision_server import _decision, _load_registry, _load_trusted_state, _store_observations


def test_discovery_telemetry_updates_only_matching_configured_route(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    observations_path = tmp_path / "observations.json"
    snapshot = {
        "ollama/example-local-model": {
            "providerId": "local-provider",
            "modelId": "example-local-model",
            "productionEligible": False,
            "telemetryStatus": "captured",
            "telemetry": {
                "capturedAt": "2026-10-20T12:00:00Z",
                "measurementId": "test-measurement",
                "metrics": {"latencyMs": 123, "available": True},
            },
        },
        "ollama/unconfigured-model": {
            "providerId": "ollama",
            "modelId": "unconfigured-model",
            "productionEligible": False,
            "telemetryStatus": "captured",
            "telemetry": {
                "capturedAt": "2026-10-20T12:00:00Z",
                "measurementId": "test-unconfigured",
                "metrics": {"latencyMs": 1},
            },
        },
    }

    result = _store_observations({"snapshot": snapshot}, observations_path)
    registry = _load_registry(registry_path, observations_path, require_production=False)

    assert result == {"accepted": 2}
    assert len(registry.snapshot["instances"]) == 1
    route = registry.snapshot["instances"][0]
    assert route["estimated_latency_ms"] == 123
    assert route["model_used"] == "example-local-model"


def test_decision_bridge_uses_existing_graph_engine_and_returns_route(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    observations_path = tmp_path / "observations.json"
    request = {
        "request_id": "openclaw-test",
        "task_class": "general",
        "summary": "OpenClaw text-generation model selection",
        "required_capabilities": ["text-generation"],
        "profile": "balanced_local_first",
        "constraints": {
            "privacy_level": "unknown",
            "external_network_allowed": True,
            "max_cloud_cost_usd": 0,
            "max_latency_ms": 120000,
            "min_quality_score": 0,
            "search_budget": {"max_candidate_routes": 100},
            "quota_budget": {"remaining_fraction": 1},
        },
        "governance": {"validation_required": True},
    }

    result = _decision({"request": request}, registry_path, observations_path, require_production=False)

    assert result["status"] == "execution_plan_ready"
    assert result["engine"] == "adaptive_graph"
    assert result["providerOverride"] == "local-provider"
    assert result["modelOverride"] == "example-local-model"
    assert result["selected_route"]["route_id"] == "local-text-generation"


def test_bridge_rejects_non_production_registry_by_default(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    with pytest.raises(ContractValidationError, match="registry_mode must be production"):
        _decision({"request": {}}, registry_path, tmp_path / "observations.json")


def test_missing_trusted_usage_ledger_fails_closed(monkeypatch, tmp_path: Path) -> None:
    telemetry_path = tmp_path / "telemetry.json"
    telemetry_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("ACCE_TRUSTED_STATE_TELEMETRY_PATH", str(telemetry_path))
    monkeypatch.setenv("ACCE_USAGE_LEDGER_PATH", str(tmp_path / "missing-ledger.json"))
    assert _load_trusted_state() is None
