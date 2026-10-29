from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from acce_optimizer.core.decision_server import _decision


def _production_registry() -> dict:
    return {
        "snapshot_id": "ci-runtime-snapshot",
        "policy_snapshot_id": "ci-policy-v1",
        "configuration_snapshot_id": "ci-configuration-v1",
        "registry_mode": "production",
        "inventory_status": "complete",
        "inventory_evidence_id": "ci-inventory-measurement",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "expected_model_count": 1,
        "expected_local_model_count": 1,
        "expected_cloud_model_count": 0,
        "capabilities": [
            {
                "capability_id": "text-generation",
                "supported_task_classes": ["general"],
            }
        ],
        "models": [
            {
                "model_ref": "local-provider/qwen3:8b",
                "provider_id": "local-provider",
                "resource_type": "local_model",
                "availability": "available",
                "operational_status": "production",
                "context_window_tokens": 8192,
                "measured_latency_ms": 500,
                "quality_score": 0.8,
                "supported_task_classes": ["general"],
                "privacy_level": "private",
                "measurement_evidence_id": "ci-qwen3-measurement",
                "tool_access": False,
            }
        ],
        "instances": [
            {
                "route_id": "local-route-qwen3",
                "capability_id": "text-generation",
                "instance_id": "local-runtime-a",
                "provider_id": "local-provider",
                "resource_type": "local_model",
                "supported_task_classes": ["general"],
                "availability": "available",
                "operational_status": "production",
                "quality_score": 0.8,
                "estimated_latency_ms": 500,
                "estimated_cloud_cost_usd": 0.0,
                "model_used": "qwen3:8b",
                "quota_metered": False,
                "monetary_metered": False,
                "context_window_tokens": 8192,
                "privacy_level": "private",
                "metadata_complete": True,
                "requires_network": False,
                "requires_tool_access": False,
            }
        ],
    }


def _payload(available: bool) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "request": {
            "request_id": "openclaw-ci-runtime-integration",
            "task_class": "general",
            "summary": "OpenClaw model routing smoke",
            "required_capabilities": ["text-generation"],
            "profile": "balanced_local_first",
            "constraints": {
                "privacy_level": "private",
                "external_network_allowed": False,
                "max_cloud_cost_usd": 0,
                "max_latency_ms": 120000,
                "min_quality_score": 0,
                "search_budget": {"max_candidate_routes": 100},
                "quota_budget": {"remaining_fraction": 1},
            },
            "governance": {"validation_required": True},
        },
        "runtime_catalog": [
            {"providerId": "local-provider", "modelId": "qwen3:8b", "available": available, "contextWindow": 8192}
        ],
        "runtime_status_required": True,
        "runtime_status": {
            "modelsCapturedAt": now,
            "usageCapturedAt": now,
            "models": [
                {"providerId": "local-provider", "modelId": "qwen3:8b", "available": available, "contextWindow": 8192}
            ],
            "usage": [],
        },
    }


def test_production_registry_route_matches_openclaw_model_id_and_returns_override(tmp_path: Path) -> None:
    registry_path = tmp_path / "production-registry.json"
    registry_path.write_text(json.dumps(_production_registry()), encoding="utf-8")

    result = _decision(
        _payload(available=True),
        registry_path,
        tmp_path / "observations.json",
    )

    assert result["status"] == "execution_plan_ready"
    assert result["providerOverride"] == "local-provider"
    assert result["modelOverride"] == "qwen3:8b"
    assert result["selected_route"]["route_id"] == "local-route-qwen3"


def test_production_registry_does_not_override_when_openclaw_reports_unavailable(tmp_path: Path) -> None:
    registry_path = tmp_path / "production-registry.json"
    registry_path.write_text(json.dumps(_production_registry()), encoding="utf-8")

    result = _decision(
        _payload(available=False),
        registry_path,
        tmp_path / "observations.json",
    )

    assert result["providerOverride"] is None
    assert result["modelOverride"] is None
