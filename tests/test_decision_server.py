from __future__ import annotations

import json
from pathlib import Path

import pytest

from acce_optimizer.core.errors import ContractValidationError
from acce_optimizer.core.engine import route_blocking_reason
from acce_optimizer.core.models import CandidateRoute, DecisionRequest
from acce_optimizer.core.decision_server import _apply_runtime_catalog, _decision, _load_registry, _load_trusted_state, _store_observations


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


def test_decision_bridge_uses_existing_graph_engine_and_returns_route(tmp_path: Path, monkeypatch) -> None:
    decision_log = tmp_path / "decisions.jsonl"
    monkeypatch.setenv("ACCE_DECISION_LOG_PATH", str(decision_log))
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
    ranking = result["ranking_result"]
    assert ranking
    assert ranking[0]["route_id"] == "local-text-generation"
    assert ranking[0]["rank"] == 1
    assert ranking[0]["score_percent"] == pytest.approx(100.0)
    assert sum(item["score_percent"] for item in ranking) == pytest.approx(100.0)
    log_entry = json.loads(decision_log.read_text(encoding="utf-8").splitlines()[0])
    assert log_entry["decision_id"] == result["decision_id"]
    assert "summary" not in log_entry["normalized_request"]
    assert log_entry["selected_route"]["route_id"] == "local-text-generation"


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


def test_task_specific_routes_win_but_general_routes_remain_fallbacks() -> None:
    request = DecisionRequest.from_mapping({
        "request_id": "task-fit-test",
        "task_class": "coding",
        "summary": "coding task",
        "required_capabilities": ["text-generation"],
    })
    general_route = CandidateRoute.from_mapping({
        "route_id": "general-route", "capability_id": "text-generation",
        "instance_id": "general", "provider_id": "local", "resource_type": "local_model",
        "availability": "available", "supported_task_classes": ["general"],
    })
    analysis_route = CandidateRoute.from_mapping({
        "route_id": "analysis-route", "capability_id": "text-generation",
        "instance_id": "analysis", "provider_id": "local", "resource_type": "local_model",
        "availability": "available", "supported_task_classes": ["analysis"],
    })
    assert route_blocking_reason(request, general_route) is None
    assert route_blocking_reason(request, analysis_route) == "unsupported_task_class"


def test_task_specific_route_takes_precedence_over_cheaper_general_route(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "examples" / "registry.json"
    snapshot = json.loads(source.read_text(encoding="utf-8"))
    snapshot["instances"].append({
        "route_id": "coding-specific",
        "capability_id": "text-generation",
        "instance_id": "coding-instance",
        "provider_id": "local-provider",
        "resource_type": "local_model",
        "supported_task_classes": ["coding"],
        "availability": "available",
        "quality_score": 0.8,
        "estimated_latency_ms": 9000,
        "estimated_cloud_cost_usd": 0.0,
        "model_used": "example-coding-model",
        "quota_metered": False,
        "monetary_metered": False,
        "context_window_tokens": 32768,
    })
    registry_path = tmp_path / "runtime-registry.json"
    registry_path.write_text(json.dumps(snapshot), encoding="utf-8")
    request = {
        "request_id": "coding-task-fit",
        "task_class": "coding",
        "summary": "coding task",
        "required_capabilities": ["text-generation"],
        "profile": "balanced_local_first",
        "constraints": {
            "privacy_level": "unknown", "external_network_allowed": False,
            "max_cloud_cost_usd": 0, "max_latency_ms": 120000,
            "min_quality_score": 0, "search_budget": {"max_candidate_routes": 100},
            "quota_budget": {"remaining_fraction": 1},
        },
        "governance": {"validation_required": True},
    }
    result = _decision({"request": request}, registry_path, tmp_path / "observations.json", require_production=False)
    assert result["status"] == "execution_plan_ready"
    assert result["selected_route"]["route_id"] == "coding-specific"
    assert result["modelOverride"] == "example-coding-model"
    assert result["ranking_result"][0]["route_id"] == "coding-specific"



def test_runtime_catalog_filters_candidates_before_graph_ranking(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    observations_path = tmp_path / "observations.json"
    request = {
        "request_id": "runtime-catalog-filter",
        "task_class": "general",
        "summary": "OpenClaw text-generation model selection",
        "required_capabilities": ["text-generation"],
        "profile": "balanced_local_first",
        "constraints": {
            "privacy_level": "unknown",
            "external_network_allowed": False,
            "max_cloud_cost_usd": 0,
            "max_latency_ms": 120000,
            "min_quality_score": 0,
            "search_budget": {"max_candidate_routes": 100},
            "quota_budget": {"remaining_fraction": 1},
        },
        "governance": {"validation_required": True},
    }

    result = _decision({
        "request": request,
        # A configured model that is not the operator-authorized route must
        # not authorize or select that route; no matching pair means no override.
        "runtime_catalog": [{"providerId": "other-provider", "modelId": "other-model"}],
    }, registry_path, observations_path, require_production=False)

    assert result["providerOverride"] is None
    assert result["modelOverride"] is None
    assert result["selected_route"] is None
    assert result["status"] != "execution_plan_ready" or result["decision_state"] != "adaptive_route_selected"


def test_runtime_catalog_allows_only_exact_authorized_pair(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    observations_path = tmp_path / "observations.json"
    request = {
        "request_id": "runtime-catalog-exact-match",
        "task_class": "general",
        "summary": "OpenClaw text-generation model selection",
        "required_capabilities": ["text-generation"],
        "profile": "balanced_local_first",
        "constraints": {
            "privacy_level": "unknown",
            "external_network_allowed": False,
            "max_cloud_cost_usd": 0,
            "max_latency_ms": 120000,
            "min_quality_score": 0,
            "search_budget": {"max_candidate_routes": 100},
            "quota_budget": {"remaining_fraction": 1},
        },
        "governance": {"validation_required": True},
    }

    result = _decision({
        "request": request,
        "runtime_catalog": [{"providerId": "local-provider", "modelId": "example-local-model"}],
    }, registry_path, observations_path, require_production=False)

    assert result["providerOverride"] == "local-provider"
    assert result["modelOverride"] == "example-local-model"
    assert result["selected_route"]["route_id"] == "local-text-generation"




def test_runtime_catalog_context_cap_is_applied_before_decision(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    registry = _load_registry(registry_path, tmp_path / "observations.json", require_production=False)
    request = {"context_estimated_input_tokens": 1000, "context_expected_output_tokens": 500}
    result = _apply_runtime_catalog(registry, request, [{
        "providerId": "local-provider",
        "modelId": "example-local-model",
        "contextWindow": 32768,
        "contextTokens": 8192,
    }])
    route = result.snapshot["instances"][0]
    assert route["route_id"] == "local-text-generation"
    assert route["context_window_tokens"] == 8192


def test_runtime_price_is_used_only_with_positive_token_estimates(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    registry = _load_registry(registry_path, tmp_path / "observations.json", require_production=False)
    request = {
        "context_estimated_input_tokens": 1000,
        "context_expected_output_tokens": 500,
    }
    result = _apply_runtime_catalog(registry, request, [{
        "providerId": "local-provider",
        "modelId": "example-local-model",
        "cost": {"input": 2.0, "output": 10.0},
    }])
    route = result.snapshot["instances"][0]
    assert route["estimated_cloud_cost_usd"] == pytest.approx(0.007)
    assert route["monetary_metered"] is True


def test_runtime_price_does_not_treat_missing_token_estimates_as_free(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    registry = _load_registry(registry_path, tmp_path / "observations.json", require_production=False)
    original_cost = registry.snapshot["instances"][0]["estimated_cloud_cost_usd"]
    result = _apply_runtime_catalog(registry, {}, [{
        "providerId": "local-provider",
        "modelId": "example-local-model",
        "cost": {"input": 2.0, "output": 10.0},
    }])
    route = result.snapshot["instances"][0]
    assert route["estimated_cloud_cost_usd"] == original_cost
    assert route["monetary_metered"] is False
