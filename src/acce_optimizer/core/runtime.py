from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from .trusted_state import TrustedRuntimeState

from .adaptive_shadow import adaptive_shadow_compare
from .engine import build_execution_plan
from .errors import ContractValidationError
from .io import read_json
from .models import DecisionRequest
from .observability import append_decision_log
from .registry import CapabilityRegistry
from .routing_policy import RoutingPolicy


@dataclass(frozen=True)
class RuntimeSnapshot:
    registry_snapshot_id: str
    policy_snapshot_id: str
    configuration_snapshot_id: str
    runtime_mode: str = "offline_reusable_runtime"

    def as_evidence(self) -> dict[str, Any]:
        return {
            "runtime_mode": self.runtime_mode,
            "registry_snapshot_id": self.registry_snapshot_id,
            "policy_snapshot_id": self.policy_snapshot_id,
            "configuration_snapshot_id": self.configuration_snapshot_id,
        }


@dataclass(frozen=True)
class EconomicPolicy:
    """Trusted monetary ledger snapshot for genuinely metered APIs."""

    monthly_cloud_budget_usd: float = 20.0
    monthly_cloud_spend_usd: float = 0.0
    cloud_quota_remaining_fraction: float = 1.0
    budget_period: str = "configured-default"

    def __post_init__(self) -> None:
        for field, value in {
            "monthly_cloud_budget_usd": self.monthly_cloud_budget_usd,
            "monthly_cloud_spend_usd": self.monthly_cloud_spend_usd,
            "cloud_quota_remaining_fraction": self.cloud_quota_remaining_fraction,
        }.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ContractValidationError(f"{field} must be a finite number")
            if value < 0:
                raise ContractValidationError(f"{field} must be >= 0")
        if self.cloud_quota_remaining_fraction > 1:
            raise ContractValidationError("cloud_quota_remaining_fraction must be <= 1")
        if not isinstance(self.budget_period, str) or not self.budget_period.strip():
            raise ContractValidationError("budget_period must be a non-empty string")


@dataclass(frozen=True)
class QuotaPolicy:
    """Trusted nonmonetary provider-quota observation supplied by OpenClaw."""

    remaining_fraction: float = 1.0
    provider_id: str | None = None
    reset_after_seconds: int | None = None
    window_seconds: int | None = None

    def __post_init__(self) -> None:
        value = self.remaining_fraction
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ContractValidationError("remaining_fraction must be a finite number")
        if not 0 <= value <= 1:
            raise ContractValidationError("remaining_fraction must be between 0 and 1")
        if self.provider_id is not None and (
            not isinstance(self.provider_id, str) or not self.provider_id.strip()
        ):
            raise ContractValidationError("provider_id must be a non-empty string or null")
        for field, item, minimum in (
            ("reset_after_seconds", self.reset_after_seconds, 0),
            ("window_seconds", self.window_seconds, 1),
        ):
            if item is not None and (
                isinstance(item, bool) or not isinstance(item, int) or item < minimum
            ):
                raise ContractValidationError(f"{field} must be an integer >= {minimum} or null")
        if (self.reset_after_seconds is None) != (self.window_seconds is None):
            raise ContractValidationError(
                "reset_after_seconds and window_seconds must be provided together"
            )
        if (
            self.reset_after_seconds is not None
            and self.window_seconds is not None
            and self.reset_after_seconds > self.window_seconds
        ):
            raise ContractValidationError("reset_after_seconds must be <= window_seconds")


@dataclass(frozen=True)
class ContextPolicy:
    """Trusted thresholds for context compaction and reset decisions."""

    compact_at_tokens: int = 196_608
    reset_at_tokens: int = 249_036
    hard_limit_tokens: int = 262_144
    compaction_enabled: bool = True

    def __post_init__(self) -> None:
        values = (self.compact_at_tokens, self.reset_at_tokens, self.hard_limit_tokens)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values):
            raise ContractValidationError("context thresholds must be positive integers")
        if not self.compact_at_tokens <= self.reset_at_tokens <= self.hard_limit_tokens:
            raise ContractValidationError(
                "context thresholds must satisfy compact_at_tokens <= reset_at_tokens <= hard_limit_tokens"
            )
        if not isinstance(self.compaction_enabled, bool):
            raise ContractValidationError("compaction_enabled must be a boolean")


class DecisionService:
    """Stable public runtime facade for ACCE decisions."""

    contract_id = "acce_optimizer.decision-service"
    contract_version = "1.4.0"
    public_contract = "DecisionService.decide(request)"

    def __init__(
        self,
        registry: CapabilityRegistry,
        decision_log_path: Path | None = None,
        economic_policy: EconomicPolicy | None = None,
        quota_policy: QuotaPolicy | None = None,
        context_policy: ContextPolicy | None = None,
        trusted_state: "TrustedRuntimeState | None" = None,
    ) -> None:
        self._registry = registry
        self._decision_log_path = decision_log_path
        if trusted_state is not None and (
            economic_policy is not None or quota_policy is not None or context_policy is not None
        ):
            raise ContractValidationError("trusted_state cannot be combined with explicit policies")
        self._economic_policy = trusted_state.economic_policy if trusted_state else (economic_policy or EconomicPolicy())
        self._quota_policy = (
            trusted_state.quota_policy
            if trusted_state
            else quota_policy
            or QuotaPolicy(
                remaining_fraction=self._economic_policy.cloud_quota_remaining_fraction
            )
        )
        self._context_policy = trusted_state.context_policy if trusted_state else (context_policy or ContextPolicy())
        self._trusted_context_current_tokens = trusted_state.context_current_tokens if trusted_state else None
        self._trusted_compaction_in_progress = trusted_state.compaction_in_progress if trusted_state else False
        self._snapshot = RuntimeSnapshot(
            registry_snapshot_id=registry.snapshot_id,
            policy_snapshot_id=registry.policy_snapshot_id,
            configuration_snapshot_id=registry.configuration_snapshot_id,
        )

    @classmethod
    def from_paths(
        cls,
        registry_path: Path,
        decision_log_path: Path | None = None,
        economic_policy: EconomicPolicy | None = None,
        quota_policy: QuotaPolicy | None = None,
        context_policy: ContextPolicy | None = None,
    ) -> "DecisionService":
        return cls(
            registry=CapabilityRegistry(read_json(registry_path)),
            decision_log_path=decision_log_path,
            economic_policy=economic_policy,
            quota_policy=quota_policy,
            context_policy=context_policy,
        )

    @property
    def runtime_snapshot(self) -> RuntimeSnapshot:
        return self._snapshot

    def decide(self, request: DecisionRequest | Mapping[str, Any]) -> dict[str, Any]:
        normalized_request = self._apply_policies(self._normalize(request))
        plan = build_execution_plan(normalized_request, self._registry)
        if self._decision_log_path is not None:
            append_decision_log(self._decision_log_path, plan)
        return plan

    def shadow_adaptive_decision(
        self,
        request: DecisionRequest | Mapping[str, Any],
        *,
        policy: RoutingPolicy | None = None,
    ) -> dict[str, Any]:
        """Compare the adaptive graph with the authoritative compatibility decision without routing."""
        normalized_request = self._apply_policies(self._normalize(request))
        authoritative_plan = build_execution_plan(normalized_request, self._registry)
        return adaptive_shadow_compare(
            normalized_request,
            authoritative_plan,
            self._registry,
            economic_policy=self._economic_policy,
            quota_policy=self._quota_policy,
            policy=policy,
        )

    def _normalize(self, request: DecisionRequest | Mapping[str, Any]) -> DecisionRequest:
        if isinstance(request, DecisionRequest):
            # Revalidate dataclass instances too; direct construction must not
            # bypass the public contract's finite/type/range guarantees.
            return DecisionRequest.from_mapping(request.normalized())
        if not isinstance(request, Mapping):
            raise ContractValidationError("request must be a DecisionRequest or mapping")
        return DecisionRequest.from_mapping(request)

    def _apply_policies(self, request: DecisionRequest) -> DecisionRequest:
        return replace(
            request,
            monthly_cloud_budget_usd=float(self._economic_policy.monthly_cloud_budget_usd),
            monthly_cloud_spend_usd=float(self._economic_policy.monthly_cloud_spend_usd),
            cloud_quota_remaining_fraction=float(self._quota_policy.remaining_fraction),
            cloud_quota_provider_id=self._quota_policy.provider_id,
            cloud_quota_reset_after_seconds=self._quota_policy.reset_after_seconds,
            cloud_quota_window_seconds=self._quota_policy.window_seconds,
            budget_period=self._economic_policy.budget_period,
            context_compact_at_tokens=self._context_policy.compact_at_tokens,
            context_reset_at_tokens=self._context_policy.reset_at_tokens,
            context_hard_limit_tokens=self._context_policy.hard_limit_tokens,
            context_compaction_enabled=self._context_policy.compaction_enabled,
            context_current_tokens=(
                self._trusted_context_current_tokens
                if self._trusted_context_current_tokens is not None
                else request.context_current_tokens
            ),
            context_compaction_in_progress=self._trusted_compaction_in_progress,
        )


def runtime_contract() -> dict[str, Any]:
    """Return the current public runtime contract and adaptive boundary."""
    return {
        "contract_id": DecisionService.contract_id,
        "contract_version": DecisionService.contract_version,
        "compatibility": "decision contract preserved while adaptive routing is validated",
        "public_service": DecisionService.public_contract,
        "encapsulated_components": [
            "normalization",
            "registry_loading",
            "policy_loading",
            "snapshot_creation",
            "authoritative_decision_engine",
            "observability",
            "decision_log",
            "execution_plan_generation",
            "economic_guardrail",
            "context_guardrail",
            "trusted_usage_ledger_adapter",
            "trusted_context_telemetry_adapter",
            "openclaw_status_read_only_adapter",
            "quota_first_graph_cost",
            "strict_production_registry_validation",
            "adaptive_graph_construction",
            "adaptive_resource_state",
            "adaptive_policy",
            "learned_route_evidence",
            "learned_user_preferences",
            "dijkstra_search",
            "astar_search",
            "adaptive_shadow_comparison",
            "shadow_evidence_aggregation",
        ],
        "constraints": {
            "authoritative_decision_engine_preserved": True,
            "adaptive_routing_enabled_for_production": False,
            "adaptive_shadow_enabled": True,
            "adaptive_graph_immutable": True,
            "governance_before_search": True,
            "learning_cannot_directly_select_routes": True,
            "openclaw_integration_enabled": False,
            "openclaw_read_only_observation_enabled": True,
            "openclaw_session_mutation_enabled": False,
            "trusted_state_file_adapters_enabled": True,
            "quota_first_graph_cost_enabled": True,
            "production_registry_validation_enabled": True,
            "production_registry_activation_enabled": False,
            "http_api_enabled": False,
            "quota_values_inferred": False,
            "subscription_quota_converted_to_usd": False,
            "model_execution_requested_by_shadow": False,
            "conversation_content_recorded_by_shadow": False,
        },
    }
