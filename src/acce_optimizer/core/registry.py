from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from typing import Any

from .errors import ContractValidationError
from .models import CandidateRoute


class CapabilityRegistry:
    """Validated immutable view of one capability-registry snapshot."""

    def __init__(self, snapshot: Mapping[str, Any], *, require_production: bool = False) -> None:
        if not isinstance(snapshot, Mapping):
            raise ContractValidationError("registry must be an object")
        copied = deepcopy(dict(snapshot))
        self._production_validation_report = (
            validate_production_registry(copied) if require_production else None
        )
        self.snapshot_id = self._snapshot_text(copied, "snapshot_id")
        self.policy_snapshot_id = self._snapshot_text(
            copied, "policy_snapshot_id", "policy-unknown"
        )
        self.configuration_snapshot_id = self._snapshot_text(
            copied, "configuration_snapshot_id", "configuration-unknown"
        )
        instances = copied.get("instances", [])
        if not isinstance(instances, list):
            raise ContractValidationError("registry.instances must be a list")

        by_capability: dict[str, list[CandidateRoute]] = defaultdict(list)
        route_ids: set[str] = set()
        for raw_instance in instances:
            route = CandidateRoute.from_mapping(raw_instance)
            if route.route_id in route_ids:
                raise ContractValidationError("registry route_id values must be unique")
            route_ids.add(route.route_id)
            by_capability[route.capability_id].append(route)

        self._snapshot = copied
        self._candidates = {
            capability_id: tuple(sorted(routes, key=lambda route: (route.exploration_priority, route.route_id)))
            for capability_id, routes in by_capability.items()
        }

    @staticmethod
    def _snapshot_text(snapshot: Mapping[str, Any], field: str, default: str | None = None) -> str:
        value = snapshot.get(field, default)
        if not isinstance(value, str) or not value.strip():
            raise ContractValidationError(f"registry.{field} must be a non-empty string")
        return value

    @property
    def snapshot(self) -> dict[str, Any]:
        """Return a defensive copy; callers cannot mutate active decisions."""
        return deepcopy(self._snapshot)

    @property
    def production_validation_report(self) -> dict[str, Any] | None:
        """Return the immutable production-readiness result when strict mode was used."""
        return deepcopy(self._production_validation_report)

    @classmethod
    def from_production_snapshot(cls, snapshot: Mapping[str, Any]) -> "CapabilityRegistry":
        """Build a registry from a production snapshot after strict validation."""
        return cls(snapshot, require_production=True)

    def candidates_for(self, capability_id: str) -> list[CandidateRoute]:
        return list(self._candidates.get(capability_id, ()))


_PLACEHOLDER_MARKERS = ("placeholder", "example", "dummy", "unknown", "todo", "tbd")
_MODEL_RESOURCE_TYPES = {"local_model", "cloud_model"}
_MODEL_AVAILABILITY = {"available", "unavailable", "disabled"}
_OPERATIONAL_STATUSES = {"production", "experimental", "disabled"}


def _production_text(data: Mapping[str, Any], field: str) -> str:
    value = data.get(field.rsplit(".", 1)[-1])
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"production registry {field} must be a non-empty string")
    if any(marker in value.casefold() for marker in _PLACEHOLDER_MARKERS):
        raise ContractValidationError(f"production registry {field} contains a placeholder value")
    return value


def _production_integer(data: Mapping[str, Any], field: str, *, minimum: int = 1) -> int:
    value = data.get(field.rsplit(".", 1)[-1])
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractValidationError(
            f"production registry {field} must be an integer >= {minimum}"
        )
    return value


def _production_score(data: Mapping[str, Any], field: str) -> float:
    value = data.get(field.rsplit(".", 1)[-1])
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"production registry {field} must be a number")
    result = float(value)
    if not 0 <= result <= 1:
        raise ContractValidationError(f"production registry {field} must be between 0 and 1")
    return result


def _production_text_list(data: Mapping[str, Any], field: str) -> tuple[str, ...]:
    value = data.get(field.rsplit(".", 1)[-1])
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ContractValidationError(
            f"production registry {field} must be a non-empty list of strings"
        )
    return tuple(value)


def _validate_measured_at(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError("production registry measured_at must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractValidationError(
            "production registry measured_at must be an RFC 3339 timestamp"
        ) from error
    if parsed.tzinfo is None:
        raise ContractValidationError("production registry measured_at must include a timezone")
    return value


def validate_production_registry(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a complete, measured production model registry without inventing metadata."""
    if not isinstance(snapshot, Mapping):
        raise ContractValidationError("production registry must be an object")
    copied = deepcopy(dict(snapshot))
    if copied.get("registry_mode") != "production":
        raise ContractValidationError("production registry registry_mode must be production")
    if copied.get("inventory_status") != "complete":
        raise ContractValidationError("production registry inventory_status must be complete")

    snapshot_id = _production_text(copied, "snapshot_id")
    policy_snapshot_id = _production_text(copied, "policy_snapshot_id")
    configuration_snapshot_id = _production_text(copied, "configuration_snapshot_id")
    evidence_id = _production_text(copied, "inventory_evidence_id")
    measured_at = _validate_measured_at(copied.get("measured_at"))
    expected_count = _production_integer(copied, "expected_model_count")
    expected_local_count = _production_integer(copied, "expected_local_model_count", minimum=0)
    expected_cloud_count = _production_integer(copied, "expected_cloud_model_count", minimum=0)
    if expected_local_count + expected_cloud_count != expected_count:
        raise ContractValidationError(
            "production registry local and cloud model counts must equal expected_model_count"
        )

    capabilities = copied.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise ContractValidationError("production registry capabilities must be a non-empty list")
    capability_ids: set[str] = set()
    for index, raw_capability in enumerate(capabilities):
        if not isinstance(raw_capability, Mapping):
            raise ContractValidationError(
                f"production registry capabilities[{index}] must be an object"
            )
        capability_id = _production_text(raw_capability, f"capabilities[{index}].capability_id")
        if capability_id in capability_ids:
            raise ContractValidationError("production registry capability_id values must be unique")
        capability_ids.add(capability_id)
        _production_text_list(
            raw_capability, f"capabilities[{index}].supported_task_classes"
        )

    models = copied.get("models")
    if not isinstance(models, list):
        raise ContractValidationError("production registry models must be a list")
    if len(models) != expected_count:
        raise ContractValidationError(
            "production registry model count must match expected_model_count"
        )

    model_inventory: dict[str, dict[str, Any]] = {}
    for index, raw_model in enumerate(models):
        if not isinstance(raw_model, Mapping):
            raise ContractValidationError(f"production registry models[{index}] must be an object")
        prefix = f"models[{index}]"
        model_ref = _production_text(raw_model, f"{prefix}.model_ref")
        provider_id = _production_text(raw_model, f"{prefix}.provider_id")
        if not model_ref.startswith(provider_id + "/"):
            raise ContractValidationError(
                f"production registry {prefix}.model_ref must be provider-qualified"
            )
        if model_ref in model_inventory:
            raise ContractValidationError("production registry model_ref values must be unique")
        resource_type = _production_text(raw_model, f"{prefix}.resource_type")
        if resource_type not in _MODEL_RESOURCE_TYPES:
            raise ContractValidationError(
                f"production registry {prefix}.resource_type is unsupported"
            )
        availability = _production_text(raw_model, f"{prefix}.availability")
        if availability not in _MODEL_AVAILABILITY:
            raise ContractValidationError(
                f"production registry {prefix}.availability is unsupported"
            )
        operational_status = _production_text(raw_model, f"{prefix}.operational_status")
        if operational_status not in _OPERATIONAL_STATUSES:
            raise ContractValidationError(
                f"production registry {prefix}.operational_status is unsupported"
            )
        if operational_status == "production" and availability != "available":
            raise ContractValidationError(
                f"production registry {prefix} production model must be available"
            )
        if operational_status == "disabled" and availability != "disabled":
            raise ContractValidationError(
                f"production registry {prefix} disabled model must have disabled availability"
            )
        context_window_tokens = _production_integer(raw_model, f"{prefix}.context_window_tokens")
        measured_latency_ms = _production_integer(raw_model, f"{prefix}.measured_latency_ms")
        quality_score = _production_score(raw_model, f"{prefix}.quality_score")
        supported_task_classes = _production_text_list(
            raw_model, f"{prefix}.supported_task_classes"
        )
        privacy_level = _production_text(raw_model, f"{prefix}.privacy_level")
        measurement_evidence_id = _production_text(
            raw_model, f"{prefix}.measurement_evidence_id"
        )
        if not isinstance(raw_model.get("tool_access"), bool):
            raise ContractValidationError(
                f"production registry {prefix}.tool_access must be a boolean"
            )
        model_inventory[model_ref] = {
            "provider_id": provider_id,
            "resource_type": resource_type,
            "availability": availability,
            "operational_status": operational_status,
            "context_window_tokens": context_window_tokens,
            "measured_latency_ms": measured_latency_ms,
            "quality_score": quality_score,
            "supported_task_classes": supported_task_classes,
            "privacy_level": privacy_level,
            "measurement_evidence_id": measurement_evidence_id,
            "tool_access": raw_model["tool_access"],
        }

    instances = copied.get("instances")
    if not isinstance(instances, list) or not instances:
        raise ContractValidationError("production registry instances must be a non-empty list")
    referenced_models: set[str] = set()
    for index, raw_instance in enumerate(instances):
        if not isinstance(raw_instance, Mapping):
            raise ContractValidationError(
                f"production registry instances[{index}] must be an object"
            )
        prefix = f"instances[{index}]"
        _production_text(raw_instance, f"{prefix}.route_id")
        _production_text(raw_instance, f"{prefix}.instance_id")
        capability_id = _production_text(raw_instance, f"{prefix}.capability_id")
        if capability_id not in capability_ids:
            raise ContractValidationError(
                f"production registry {prefix}.capability_id is not declared"
            )
        resource_type = _production_text(raw_instance, f"{prefix}.resource_type")
        if resource_type not in _MODEL_RESOURCE_TYPES:
            continue
        model_ref = _production_text(raw_instance, f"{prefix}.model_used")
        inventory = model_inventory.get(model_ref)
        if inventory is None:
            raise ContractValidationError(
                f"production registry {prefix}.model_used is not in the model inventory"
            )
        route_provider_id = _production_text(raw_instance, f"{prefix}.provider_id")
        if route_provider_id != inventory["provider_id"]:
            raise ContractValidationError(
                f"production registry {prefix}.provider_id does not match its model"
            )
        if resource_type != inventory["resource_type"]:
            raise ContractValidationError(
                f"production registry {prefix}.resource_type does not match its model"
            )
        if raw_instance.get("metadata_complete") is not True:
            raise ContractValidationError(
                f"production registry {prefix}.metadata_complete must be true"
            )
        expected_network = resource_type == "cloud_model"
        if raw_instance.get("requires_network") is not expected_network:
            raise ContractValidationError(
                f"production registry {prefix}.requires_network does not match its resource type"
            )
        expected_quota_metered = resource_type == "cloud_model"
        if raw_instance.get("quota_metered") is not expected_quota_metered:
            raise ContractValidationError(
                f"production registry {prefix}.quota_metered does not match its resource type"
            )
        if not isinstance(raw_instance.get("monetary_metered"), bool):
            raise ContractValidationError(
                f"production registry {prefix}.monetary_metered must be a boolean"
            )
        requires_tool_access = raw_instance.get("requires_tool_access")
        if not isinstance(requires_tool_access, bool):
            raise ContractValidationError(
                f"production registry {prefix}.requires_tool_access must be a boolean"
            )
        if requires_tool_access and not inventory["tool_access"]:
            raise ContractValidationError(
                f"production registry {prefix} claims unmeasured tool access"
            )
        route_window = _production_integer(raw_instance, f"{prefix}.context_window_tokens")
        if route_window > inventory["context_window_tokens"]:
            raise ContractValidationError(
                f"production registry {prefix}.context_window_tokens exceeds the measured model window"
            )
        route_latency = _production_integer(raw_instance, f"{prefix}.estimated_latency_ms")
        if route_latency != inventory["measured_latency_ms"]:
            raise ContractValidationError(
                f"production registry {prefix}.estimated_latency_ms must use the measured value"
            )
        route_quality = _production_score(raw_instance, f"{prefix}.quality_score")
        if route_quality != inventory["quality_score"]:
            raise ContractValidationError(
                f"production registry {prefix}.quality_score must use the measured value"
            )
        route_tasks = set(_production_text_list(raw_instance, f"{prefix}.supported_task_classes"))
        if not route_tasks.issubset(set(inventory["supported_task_classes"])):
            raise ContractValidationError(
                f"production registry {prefix}.supported_task_classes exceed measured support"
            )
        route_privacy = _production_text(raw_instance, f"{prefix}.privacy_level")
        if route_privacy != inventory["privacy_level"]:
            raise ContractValidationError(
                f"production registry {prefix}.privacy_level does not match its model"
            )
        route_availability = _production_text(raw_instance, f"{prefix}.availability")
        if route_availability != inventory["availability"]:
            raise ContractValidationError(
                f"production registry {prefix}.availability does not match its model"
            )
        referenced_models.add(model_ref)

    unreferenced = sorted(set(model_inventory) - referenced_models)
    if unreferenced:
        raise ContractValidationError(
            "production registry every inventoried model must have at least one route"
        )

    validated_local_count = sum(
        item["resource_type"] == "local_model" for item in model_inventory.values()
    )
    validated_cloud_count = sum(
        item["resource_type"] == "cloud_model" for item in model_inventory.values()
    )
    if validated_local_count != expected_local_count:
        raise ContractValidationError(
            "production registry local model count must match expected_local_model_count"
        )
    if validated_cloud_count != expected_cloud_count:
        raise ContractValidationError(
            "production registry cloud model count must match expected_cloud_model_count"
        )

    canonical = json.dumps(copied, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "status": "production_registry_validated",
        "registry_mode": "production",
        "snapshot_id": snapshot_id,
        "policy_snapshot_id": policy_snapshot_id,
        "configuration_snapshot_id": configuration_snapshot_id,
        "inventory_evidence_id": evidence_id,
        "measured_at": measured_at,
        "expected_model_count": expected_count,
        "expected_local_model_count": expected_local_count,
        "expected_cloud_model_count": expected_cloud_count,
        "validated_model_count": len(model_inventory),
        "validated_local_model_count": validated_local_count,
        "validated_cloud_model_count": validated_cloud_count,
        "validated_route_count": len(instances),
        "available_model_count": sum(
            item["availability"] == "available" for item in model_inventory.values()
        ),
        "production_model_count": sum(
            item["operational_status"] == "production" for item in model_inventory.values()
        ),
        "experimental_model_count": sum(
            item["operational_status"] == "experimental" for item in model_inventory.values()
        ),
        "disabled_model_count": sum(
            item["operational_status"] == "disabled" for item in model_inventory.values()
        ),
        "model_refs": sorted(model_inventory),
        "snapshot_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "placeholder_values_allowed": False,
        "decision_execution_enabled": False,
    }
