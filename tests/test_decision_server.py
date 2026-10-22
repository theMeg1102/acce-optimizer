from __future__ import annotations

import json
from pathlib import Path

import pytest

from acce_optimizer.core.errors import ContractValidationError
from acce_optimizer.core.engine import route_blocking_reason
from acce_optimizer.core.models import CandidateRoute, DecisionRequest
from acce_optimizer.core.registry import CapabilityRegistry
from acce_optimizer.core.decision_server import _apply_runtime_catalog, _apply_runtime_status, _decision, _load_registry, _load_trusted_state, _store_observations, _store_route_outcome, _store_issued_decision


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
        "preferred_route_id": "local-text-generation",
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


def test_runtime_price_with_unmodeled_cache_rates_preserves_registry_estimate(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    registry = _load_registry(registry_path, tmp_path / "observations.json", require_production=False)
    original = registry.snapshot["instances"][0]
    original_cost = original["estimated_cloud_cost_usd"]
    result = _apply_runtime_catalog(registry, {
        "context_estimated_input_tokens": 1000,
        "context_expected_output_tokens": 500,
    }, [{
        "providerId": "local-provider",
        "modelId": "example-local-model",
        "cost": {"input": 2.0, "output": 10.0, "cacheRead": 0.5},
    }])
    route = result.snapshot["instances"][0]
    assert route["estimated_cloud_cost_usd"] == original_cost
    assert route["monetary_metered"] is False


def test_explicit_preferred_route_is_preserved_in_normalized_decision_request() -> None:
    request = DecisionRequest.from_mapping({
        "request_id": "preferred-route",
        "task_class": "coding",
        "summary": "coding task",
        "preferred_route_id": "route-local",
        "constraints": {},
        "governance": {},
    })
    assert request.preferred_route_id == "route-local"
    assert request.normalized()["preferred_route_id"] == "route-local"


def test_preferred_route_id_is_optional_for_backward_compatibility() -> None:
    request = DecisionRequest.from_mapping({
        "request_id": "no-preference",
        "task_class": "general",
        "summary": "general task",
        "constraints": {},
        "governance": {},
    })
    assert request.preferred_route_id is None
    assert "preferred_route_id" not in request.normalized()


def test_route_outcomes_are_authorized_bounded_and_task_signature_scoped(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    outcomes_path = tmp_path / "route-outcomes.json"
    payload = {
        "route_id": "local-text-generation",
        "provider_id": "local-provider",
        "model_id": "example-local-model",
        "task_signature": "coding|programming",
        "outcome": "success",
        "decision_id": "decision-safe-id",
    }
    for _ in range(5):
        assert _store_route_outcome(payload, registry_path, outcomes_path, require_production=False)["accepted"] == 1

    registry = _load_registry(
        registry_path,
        tmp_path / "observations.json",
        require_production=False,
        route_outcomes_path=outcomes_path,
        task_signature="coding|programming",
    )
    route = registry.candidates_for("text-generation")[0]
    assert route.observed_sample_count == 5
    assert route.observed_success_rate is not None
    assert route.observed_success_rate > route.quality_score

    unrelated = _load_registry(
        registry_path,
        tmp_path / "observations.json",
        require_production=False,
        route_outcomes_path=outcomes_path,
        task_signature="research",
    )
    assert unrelated.candidates_for("text-generation")[0].observed_sample_count == 0


def test_route_outcome_endpoint_rejects_unapproved_routes(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    with pytest.raises(ValueError, match="operator-authorized"):
        _store_route_outcome({
            "route_id": "invented-route",
            "provider_id": "invented-provider",
            "model_id": "invented-model",
            "task_signature": "coding",
            "outcome": "success",
        }, registry_path, tmp_path / "outcomes.json", require_production=False)


def test_preferred_route_order_is_normalized_as_a_bounded_tuple() -> None:
    request = DecisionRequest.from_mapping({
        "request_id": "route-template",
        "task_class": "coding",
        "summary": "coding task",
        "preferred_route_order": ["route-a", "route-b"],
    })
    assert request.preferred_route_order == ("route-a", "route-b")
    assert request.normalized()["preferred_route_order"] == ["route-a", "route-b"]


def test_observation_sync_merges_models_and_applies_conservative_context_budget(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    observations_path = tmp_path / "observations.json"
    first = {
        "local-provider/example-local-model": {
            "providerId": "local-provider",
            "modelId": "example-local-model",
            "productionEligible": False,
            "telemetryStatus": "captured",
            "telemetry": {"capturedAt": "2026-10-22T00:00:00Z", "measurementId": "m1",
                          "metrics": {"latencyMs": 120, "contextTokenBudget": 8192}},
        }
    }
    second = {
        "other-provider/other-model": {
            "providerId": "other-provider",
            "modelId": "other-model",
            "productionEligible": False,
            "telemetryStatus": "captured",
            "telemetry": {"capturedAt": "2026-10-22T00:01:00Z", "measurementId": "m2",
                          "metrics": {"latencyMs": 240}},
        }
    }
    _store_observations({"snapshot": first}, observations_path)
    _store_observations({"snapshot": second}, observations_path)
    saved = json.loads(observations_path.read_text(encoding="utf-8"))
    assert "local-provider/example-local-model" in saved
    assert "other-provider/other-model" in saved
    registry = _load_registry(registry_path, observations_path, require_production=False)
    route = registry.candidates_for("text-generation")[0]
    assert route.context_window_tokens == 8192


def test_route_outcome_requires_matching_issued_decision_and_is_one_time(tmp_path: Path) -> None:
    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    outcomes_path = tmp_path / "route-outcomes.json"
    issued_path = tmp_path / "issued-decisions.json"
    decision = {
        "decision_id": "decision-123",
        "task_signature": "coding|programming",
        "selected_route": {
            "route_id": "local-text-generation",
            "provider_id": "local-provider",
            "model_used": "example-local-model",
        },
    }
    _store_issued_decision(decision, issued_path)
    outcome = {
        "decision_id": "decision-123",
        "route_id": "local-text-generation",
        "provider_id": "local-provider",
        "model_id": "example-local-model",
        "task_signature": "coding|programming",
        "outcome": "success",
    }
    assert _store_route_outcome(outcome, registry_path, outcomes_path, require_production=False, issued_decisions_path=issued_path)["accepted"] == 1
    with pytest.raises(ValueError, match="recently issued"):
        _store_route_outcome(outcome, registry_path, outcomes_path, require_production=False, issued_decisions_path=issued_path)


def test_runtime_status_requires_positive_availability_and_applies_context_cap(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    registry = _load_registry(registry_path, tmp_path / "observations.json", require_production=False)
    captured_at = datetime.now(timezone.utc).isoformat()
    status = {
        "modelsCapturedAt": captured_at,
        "usageCapturedAt": captured_at,
        "models": [{
            "providerId": "local-provider",
            "modelId": "example-local-model",
            "available": True,
            "contextWindow": 32768,
            "contextTokens": 8192,
        }],
        "usage": [],
    }
    admitted = _apply_runtime_status(registry, status, required=True)
    assert admitted.candidates_for("text-generation")[0].context_window_tokens == 8192

    status["models"][0]["available"] = None
    unavailable = _apply_runtime_status(registry, status, required=True)
    assert unavailable.candidates_for("text-generation") == []


def test_missing_or_stale_runtime_status_fails_closed_only_when_required(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    registry = _load_registry(registry_path, tmp_path / "observations.json", require_production=False)
    assert _apply_runtime_status(registry, None, required=False).candidates_for("text-generation")
    stale = {
        "modelsCapturedAt": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "usageCapturedAt": "",
        "models": [{"providerId": "local-provider", "modelId": "example-local-model", "available": True}],
        "usage": [],
    }
    assert _apply_runtime_status(registry, stale, required=True).candidates_for("text-generation") == []


def test_runtime_usage_filters_exhausted_or_unmetered_cloud_routes(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    registry_path = Path(__file__).parents[1] / "examples" / "registry.json"
    registry = _load_registry(registry_path, tmp_path / "observations.json", require_production=False)
    snapshot = registry.snapshot
    cloud_route = dict(snapshot["instances"][0])
    cloud_route.update({
        "route_id": "cloud-text-generation",
        "instance_id": "cloud-example",
        "provider_id": "cloud-provider",
        "resource_type": "cloud_model",
        "model_used": "cloud-model",
        "quota_metered": True,
        "estimated_cloud_cost_usd": 0.02,
        "monetary_metered": True,
    })
    snapshot["instances"].append(cloud_route)
    registry = CapabilityRegistry(snapshot)
    captured_at = datetime.now(timezone.utc).isoformat()
    status = {
        "modelsCapturedAt": captured_at,
        "usageCapturedAt": captured_at,
        "models": [
            {"providerId": "local-provider", "modelId": "example-local-model", "available": True},
            {"providerId": "cloud-provider", "modelId": "cloud-model", "available": True},
        ],
        "usage": [{"providerId": "cloud-provider", "remainingFraction": 0.25}],
    }
    admitted = _apply_runtime_status(registry, status, required=True)
    routes = {route.route_id: route for route in admitted.candidates_for("text-generation")}
    assert routes["cloud-text-generation"].runtime_quota_remaining_fraction == pytest.approx(0.25)

    status["usage"] = [{"providerId": "cloud-provider", "remainingFraction": 0.0}]
    exhausted = _apply_runtime_status(registry, status, required=True)
    assert "cloud-text-generation" not in {route.route_id for route in exhausted.candidates_for("text-generation")}

    status["usageCapturedAt"] = ""
    stale = _apply_runtime_status(registry, status, required=True)
    assert "cloud-text-generation" not in {route.route_id for route in stale.candidates_for("text-generation")}
