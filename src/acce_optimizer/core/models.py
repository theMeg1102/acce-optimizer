from __future__ import annotations

from dataclasses import dataclass
import math
from math import ceil
from collections.abc import Mapping
from typing import Any

from .errors import ContractValidationError


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field} must be an object")
    return value


def _required_text(data: Mapping[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} must be a non-empty string")
    return value


def _text(value: Any, field: str, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} must be a non-empty string or null")
    return value


def _bool(value: Any, field: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ContractValidationError(f"{field} must be a boolean")
    return value


def _number(
    value: Any,
    field: str,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    if value is None:
        value = default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ContractValidationError(f"{field} must be a finite number")
    if result < minimum or (maximum is not None and result > maximum):
        limit = f" between {minimum} and {maximum}" if maximum is not None else f" >= {minimum}"
        raise ContractValidationError(f"{field} must be{limit}")
    return result


def _integer(value: Any, field: str, default: int, *, minimum: int = 0) -> int:
    if value is None:
        value = default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field} must be an integer")
    if value < minimum:
        raise ContractValidationError(f"{field} must be >= {minimum}")
    return value


def _optional_integer(value: Any, field: str, *, minimum: int = 1) -> int | None:
    if value is None:
        return None
    return _integer(value, field, minimum, minimum=minimum)


def _text_list(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ContractValidationError(f"{field} must be a list of non-empty strings")
    return tuple(value)


def _as_bool_or_list(value: Any, default: bool | tuple[str, ...]) -> bool | tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, list):
        return _text_list(value, "constraints.tools_allowed")
    if isinstance(value, bool):
        return value
    raise ContractValidationError("constraints.tools_allowed must be a boolean or list of non-empty strings")


@dataclass(frozen=True)
class DecisionRequest:
    request_id: str
    task_class: str
    summary: str
    required_capabilities: tuple[str, ...]
    profile: str
    external_network_allowed: bool
    tools_allowed: bool | tuple[str, ...]
    approval_required: bool
    approval_granted: bool
    validation_required: bool
    clarification_required: bool
    privacy_level: str
    max_cloud_cost_usd: float
    max_latency_ms: int
    min_quality_score: float
    search_budget_max_candidate_routes: int
    early_exit_enabled: bool
    early_exit_global_cost_threshold: float
    risk_level: str
    sensitivity: str
    urgency: str
    monthly_cloud_budget_usd: float
    monthly_cloud_spend_usd: float
    cloud_quota_remaining_fraction: float
    cloud_quota_provider_id: str | None
    cloud_quota_reset_after_seconds: int | None
    cloud_quota_window_seconds: int | None
    budget_period: str
    context_current_tokens: int
    context_estimated_input_tokens: int
    context_expected_output_tokens: int
    context_compact_at_tokens: int
    context_reset_at_tokens: int
    context_hard_limit_tokens: int
    context_compaction_enabled: bool
    context_compaction_in_progress: bool

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DecisionRequest":
        data = _mapping(data, "request")
        constraints = _mapping(data.get("constraints", {}), "constraints")
        governance = _mapping(data.get("governance", {}), "governance")
        search_budget = _mapping(constraints.get("search_budget", {}), "constraints.search_budget")
        economic_budget = _mapping(
            constraints.get("economic_budget", {}), "constraints.economic_budget"
        )
        quota_budget = _mapping(
            constraints.get("quota_budget", {}), "constraints.quota_budget"
        )
        context_budget = _mapping(
            constraints.get("context_budget", {}), "constraints.context_budget"
        )
        external_network_allowed = constraints.get(
            "external_network_allowed",
            constraints.get("allow_external_network", False),
        )
        summary = _required_text(data, "summary")
        compact_at = _integer(
            context_budget.get("compact_at_tokens"),
            "constraints.context_budget.compact_at_tokens",
            196_608,
            minimum=1,
        )
        reset_at = _integer(
            context_budget.get("reset_at_tokens"),
            "constraints.context_budget.reset_at_tokens",
            249_036,
            minimum=1,
        )
        hard_limit = _integer(
            context_budget.get("hard_limit_tokens"),
            "constraints.context_budget.hard_limit_tokens",
            262_144,
            minimum=1,
        )
        if not compact_at <= reset_at <= hard_limit:
            raise ContractValidationError(
                "context thresholds must satisfy compact_at_tokens <= reset_at_tokens <= hard_limit_tokens"
            )
        monthly_budget = _number(
            economic_budget.get("monthly_cloud_budget_usd"),
            "constraints.economic_budget.monthly_cloud_budget_usd",
            20.0,
        )
        monthly_spend = _number(
            economic_budget.get("monthly_cloud_spend_usd"),
            "constraints.economic_budget.monthly_cloud_spend_usd",
            0.0,
        )
        quota_reset_after = _optional_integer(
            quota_budget.get("reset_after_seconds"),
            "constraints.quota_budget.reset_after_seconds",
            minimum=0,
        )
        quota_window = _optional_integer(
            quota_budget.get("window_seconds"),
            "constraints.quota_budget.window_seconds",
            minimum=1,
        )
        if (quota_reset_after is None) != (quota_window is None):
            raise ContractValidationError(
                "quota reset_after_seconds and window_seconds must be provided together"
            )
        if quota_reset_after is not None and quota_window is not None and quota_reset_after > quota_window:
            raise ContractValidationError(
                "quota reset_after_seconds must be <= window_seconds"
            )
        urgency = _text(data.get("urgency"), "urgency", "normal")
        if urgency not in {"normal", "urgent"}:
            raise ContractValidationError("urgency must be normal or urgent")
        return cls(
            request_id=_required_text(data, "request_id"),
            task_class=_required_text(data, "task_class"),
            summary=summary,
            required_capabilities=_text_list(data.get("required_capabilities", []), "required_capabilities"),
            profile=_text(data.get("profile"), "profile", "balanced"),
            external_network_allowed=_bool(external_network_allowed, "constraints.external_network_allowed", False),
            tools_allowed=_as_bool_or_list(constraints.get("tools_allowed", False), False),
            approval_required=_bool(governance.get("approval_required"), "governance.approval_required", False),
            approval_granted=_bool(governance.get("approval_granted"), "governance.approval_granted", False),
            validation_required=_bool(governance.get("validation_required"), "governance.validation_required", True),
            clarification_required=_bool(governance.get("clarification_required"), "governance.clarification_required", False),
            privacy_level=_text(constraints.get("privacy_level", data.get("sensitivity")), "constraints.privacy_level", "unknown"),
            max_cloud_cost_usd=_number(constraints.get("max_cloud_cost_usd"), "constraints.max_cloud_cost_usd", 0.0),
            max_latency_ms=_integer(constraints.get("max_latency_ms"), "constraints.max_latency_ms", 10_000),
            min_quality_score=_number(constraints.get("min_quality_score"), "constraints.min_quality_score", 0.0, maximum=1.0),
            search_budget_max_candidate_routes=_integer(search_budget.get("max_candidate_routes"), "constraints.search_budget.max_candidate_routes", 100),
            early_exit_enabled=_bool(search_budget.get("early_exit_enabled"), "constraints.search_budget.early_exit_enabled", True),
            early_exit_global_cost_threshold=_number(search_budget.get("early_exit_global_cost_threshold"), "constraints.search_budget.early_exit_global_cost_threshold", 0.0),
            risk_level=_text(data.get("risk_level"), "risk_level", "low"),
            sensitivity=_text(data.get("sensitivity"), "sensitivity", "unknown"),
            urgency=_text(data.get("urgency"), "urgency", "normal"),
            monthly_cloud_budget_usd=monthly_budget,
            monthly_cloud_spend_usd=monthly_spend,
            cloud_quota_remaining_fraction=_number(
                quota_budget.get(
                    "remaining_fraction",
                    economic_budget.get("cloud_quota_remaining_fraction"),
                ),
                "constraints.quota_budget.remaining_fraction",
                1.0,
                maximum=1.0,
            ),
            cloud_quota_provider_id=_optional_text(
                quota_budget.get("provider_id"),
                "constraints.quota_budget.provider_id",
            ),
            cloud_quota_reset_after_seconds=quota_reset_after,
            cloud_quota_window_seconds=quota_window,
            budget_period=_text(
                economic_budget.get("budget_period"),
                "constraints.economic_budget.budget_period",
                "configured-default",
            ),
            context_current_tokens=_integer(
                context_budget.get("current_tokens"),
                "constraints.context_budget.current_tokens",
                0,
            ),
            context_estimated_input_tokens=_integer(
                context_budget.get("estimated_input_tokens"),
                "constraints.context_budget.estimated_input_tokens",
                max(1, ceil(len(summary) / 4)),
            ),
            context_expected_output_tokens=_integer(
                context_budget.get("expected_output_tokens"),
                "constraints.context_budget.expected_output_tokens",
                1_024,
            ),
            context_compact_at_tokens=compact_at,
            context_reset_at_tokens=reset_at,
            context_hard_limit_tokens=hard_limit,
            context_compaction_enabled=_bool(
                context_budget.get("compaction_enabled"),
                "constraints.context_budget.compaction_enabled",
                True,
            ),
            context_compaction_in_progress=_bool(
                context_budget.get("compaction_in_progress"),
                "constraints.context_budget.compaction_in_progress",
                False,
            ),
        )

    def normalized(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "task_class": self.task_class,
            "summary": self.summary,
            "required_capabilities": list(self.required_capabilities),
            "profile": self.profile,
            "constraints": {
                "external_network_allowed": self.external_network_allowed,
                "tools_allowed": self.tools_allowed
                if isinstance(self.tools_allowed, bool)
                else list(self.tools_allowed),
                "privacy_level": self.privacy_level,
                "max_cloud_cost_usd": self.max_cloud_cost_usd,
                "max_latency_ms": self.max_latency_ms,
                "min_quality_score": self.min_quality_score,
                "search_budget": {
                    "max_candidate_routes": self.search_budget_max_candidate_routes,
                    "early_exit_enabled": self.early_exit_enabled,
                    "early_exit_global_cost_threshold": self.early_exit_global_cost_threshold,
                },
                "economic_budget": {
                    "monthly_cloud_budget_usd": self.monthly_cloud_budget_usd,
                    "monthly_cloud_spend_usd": self.monthly_cloud_spend_usd,
                    "cloud_quota_remaining_fraction": self.cloud_quota_remaining_fraction,
                    "budget_period": self.budget_period,
                },
                "quota_budget": {
                    "provider_id": self.cloud_quota_provider_id,
                    "remaining_fraction": self.cloud_quota_remaining_fraction,
                    "reset_after_seconds": self.cloud_quota_reset_after_seconds,
                    "window_seconds": self.cloud_quota_window_seconds,
                },
                "context_budget": {
                    "current_tokens": self.context_current_tokens,
                    "estimated_input_tokens": self.context_estimated_input_tokens,
                    "expected_output_tokens": self.context_expected_output_tokens,
                    "compact_at_tokens": self.context_compact_at_tokens,
                    "reset_at_tokens": self.context_reset_at_tokens,
                    "hard_limit_tokens": self.context_hard_limit_tokens,
                    "compaction_enabled": self.context_compaction_enabled,
                    "compaction_in_progress": self.context_compaction_in_progress,
                },
            },
            "governance": {
                "approval_required": self.approval_required,
                "approval_granted": self.approval_granted,
                "validation_required": self.validation_required,
                "clarification_required": self.clarification_required,
            },
            "risk_level": self.risk_level,
            "sensitivity": self.sensitivity,
            **({"urgency": self.urgency} if self.urgency != "normal" else {}),
        }


@dataclass(frozen=True)
class CandidateRoute:
    route_id: str
    capability_id: str
    instance_id: str
    provider_id: str
    resource_type: str
    requires_network: bool
    external_network_allowed: bool
    requires_tool_access: bool
    tool_id: str | None
    requires_approval: bool
    approval_required: bool
    requires_validation: bool
    privacy_level: str
    supported_task_classes: tuple[str, ...]
    availability: str
    estimated_cloud_cost_usd: float
    estimated_latency_ms: int
    quality_score: float
    privacy_penalty: float
    risk_score: float
    availability_penalty: float
    complexity_score: float
    exploration_priority: int
    early_exit_eligible: bool
    fallback_for: str | None
    metadata_complete: bool
    model_used: str | None
    quota_metered: bool
    monetary_metered: bool
    context_window_tokens: int | None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CandidateRoute":
        data = _mapping(data, "candidate route")
        resource_type = _required_text(data, "resource_type")
        return cls(
            route_id=_required_text(data, "route_id"),
            capability_id=_required_text(data, "capability_id"),
            instance_id=_required_text(data, "instance_id"),
            provider_id=_required_text(data, "provider_id"),
            resource_type=resource_type,
            requires_network=_bool(data.get("requires_network"), "requires_network", False),
            external_network_allowed=_bool(data.get("external_network_allowed"), "external_network_allowed", True),
            requires_tool_access=_bool(data.get("requires_tool_access"), "requires_tool_access", False),
            tool_id=_optional_text(data.get("tool_id"), "tool_id"),
            requires_approval=_bool(data.get("requires_approval"), "requires_approval", False),
            approval_required=_bool(data.get("approval_required", data.get("requires_approval")), "approval_required", False),
            requires_validation=_bool(data.get("requires_validation"), "requires_validation", False),
            privacy_level=_text(data.get("privacy_level"), "privacy_level", "internal"),
            supported_task_classes=_text_list(data.get("supported_task_classes", []), "supported_task_classes"),
            availability=_text(data.get("availability"), "availability", "unknown"),
            estimated_cloud_cost_usd=_number(data.get("estimated_cloud_cost_usd"), "estimated_cloud_cost_usd", 0.0),
            estimated_latency_ms=_integer(data.get("estimated_latency_ms"), "estimated_latency_ms", 0),
            quality_score=_number(data.get("quality_score"), "quality_score", 0.0, maximum=1.0),
            privacy_penalty=_number(data.get("privacy_penalty"), "privacy_penalty", 0.0),
            risk_score=_number(data.get("risk_score"), "risk_score", 0.0),
            availability_penalty=_number(data.get("availability_penalty"), "availability_penalty", 0.0),
            complexity_score=_number(data.get("complexity_score"), "complexity_score", 0.0),
            exploration_priority=_integer(data.get("exploration_priority"), "exploration_priority", 100),
            early_exit_eligible=_bool(data.get("early_exit_eligible"), "early_exit_eligible", False),
            fallback_for=_optional_text(data.get("fallback_for"), "fallback_for"),
            metadata_complete=_bool(data.get("metadata_complete"), "metadata_complete", True),
            model_used=_optional_text(data.get("model_used"), "model_used"),
            quota_metered=_bool(
                data.get("quota_metered"),
                "quota_metered",
                resource_type == "cloud_model",
            ),
            monetary_metered=_bool(
                data.get("monetary_metered"),
                "monetary_metered",
                _number(
                    data.get("estimated_cloud_cost_usd"),
                    "estimated_cloud_cost_usd",
                    0.0,
                )
                > 0.0,
            ),
            context_window_tokens=_optional_integer(
                data.get("context_window_tokens"), "context_window_tokens"
            ),
        )

    def as_evidence(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "capability_id": self.capability_id,
            "instance_id": self.instance_id,
            "provider_id": self.provider_id,
            "resource_type": self.resource_type,
            "requires_network": self.requires_network,
            "external_network_allowed": self.external_network_allowed,
            "requires_tool_access": self.requires_tool_access,
            "tool_id": self.tool_id,
            "requires_approval": self.requires_approval,
            "approval_required": self.approval_required,
            "requires_validation": self.requires_validation,
            "privacy_level": self.privacy_level,
            "supported_task_classes": list(self.supported_task_classes),
            "availability": self.availability,
            "estimated_cloud_cost_usd": self.estimated_cloud_cost_usd,
            "estimated_latency_ms": self.estimated_latency_ms,
            "quality_score": self.quality_score,
            "privacy_penalty": self.privacy_penalty,
            "risk_score": self.risk_score,
            "availability_penalty": self.availability_penalty,
            "complexity_score": self.complexity_score,
            "exploration_priority": self.exploration_priority,
            "early_exit_eligible": self.early_exit_eligible,
            "fallback_for": self.fallback_for,
            "metadata_complete": self.metadata_complete,
            "model_used": self.model_used,
            "quota_metered": self.quota_metered,
            "monetary_metered": self.monetary_metered,
            "context_window_tokens": self.context_window_tokens,
        }
