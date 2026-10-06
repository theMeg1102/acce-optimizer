from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .resource_state import ResourceState
from .errors import ContractValidationError
from .graph import GraphEdge, GraphNode
from .learning import LearnedPreference, LearnedRouteEstimate

PreferenceMode = Literal["auto", "ask", "learned"]
Urgency = Literal["normal", "urgent"]


@dataclass(frozen=True)
class RoutingPolicy:
    """Deterministic policy applied before and during adaptive graph search."""

    minimum_quality_threshold: float = 0.75

    economic_weight: float = 1.0
    quota_weight: float = 3.0
    latency_weight: float = 1.0
    quality_weight: float = 2.0
    retry_weight: float = 2.0
    fallback_weight: float = 2.0
    privacy_weight: float = 2.0
    risk_weight: float = 2.0
    complexity_weight: float = 1.0

    local_preference_factor: float = 0.80
    quota_scarcity_weight: float = 2.0
    budget_scarcity_weight: float = 2.0

    # Preference-learning governance.
    preference_mode: PreferenceMode = "auto"
    preference_observation_count: int = 5
    preference_agreement_threshold: float = 0.85
    demand_similarity_threshold: float = 0.80
    task_similarity_threshold: float = 0.80

    # Strong local-first policy. Cloud must provide a material advantage
    # before overriding a local route that already satisfies quality.
    cloud_override_threshold_normal: float = 0.30
    cloud_override_threshold_urgent: float = 0.10

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_quality_threshold <= 1.0:
            raise ContractValidationError(
                "minimum_quality_threshold must be between 0 and 1"
            )
        if not 0.0 < self.local_preference_factor <= 1.0:
            raise ContractValidationError(
                "local_preference_factor must be greater than 0 and <= 1"
            )
        if self.preference_observation_count < 1 or self.preference_observation_count % 2 == 0:
            raise ContractValidationError(
                "preference_observation_count must be a positive odd integer"
            )
        for field in (
            "preference_agreement_threshold",
            "demand_similarity_threshold",
            "task_similarity_threshold",
            "cloud_override_threshold_normal",
            "cloud_override_threshold_urgent",
        ):
            value = getattr(self, field)
            if not 0.0 <= value <= 1.0:
                raise ContractValidationError(f"{field} must be between 0 and 1")

        for field in (
            "economic_weight",
            "quota_weight",
            "latency_weight",
            "quality_weight",
            "retry_weight",
            "fallback_weight",
            "privacy_weight",
            "risk_weight",
            "complexity_weight",
            "quota_scarcity_weight",
            "budget_scarcity_weight",
        ):
            if getattr(self, field) < 0:
                raise ContractValidationError(f"{field} must be non-negative")


def route_is_governed(
    node: GraphNode,
    estimate: LearnedRouteEstimate | None,
    policy: RoutingPolicy,
) -> bool:
    """Apply hard governance before optimization."""

    if not node.authorized or not node.available:
        return False
    if estimate is not None and estimate.quality_score < policy.minimum_quality_threshold:
        return False
    return True


def next_preference_observation_count(
    evidence_count: int,
    policy: RoutingPolicy,
) -> int:
    """Return the next odd evidence threshold for preference promotion.

    Evidence thresholds grow incrementally from the configured starting
    threshold (5 by default) to 7, 9, 11, and so on. A preference is never
    promoted merely because its evidence count is high; promotion is
    evaluated at one of these governed odd thresholds.
    """

    if evidence_count < 0:
        raise ContractValidationError("evidence_count must be >= 0")
    start = policy.preference_observation_count
    if start < 1 or start % 2 == 0:
        raise ContractValidationError(
            "preference_observation_count must be a positive odd integer"
        )
    if evidence_count < start:
        return start
    return start + 2 * ((evidence_count - start) // 2 + 1)


def preference_is_promotable(
    preference: LearnedPreference,
    *,
    demand_similarity: float,
    task_similarity: float,
    policy: RoutingPolicy,
) -> bool:
    """Return whether evidence is strong enough to automate a user preference."""

    if policy.preference_mode != "learned":
        return False
    threshold = policy.preference_observation_count
    if preference.evidence_count < threshold:
        return False
    if preference.evidence_count % 2 == 0:
        return False
    if preference.agreement_rate < policy.preference_agreement_threshold:
        return False
    if demand_similarity < policy.demand_similarity_threshold:
        return False
    if task_similarity < policy.task_similarity_threshold:
        return False
    return preference.confidence >= policy.preference_agreement_threshold


def cloud_override_allowed(
    *,
    local_estimate: LearnedRouteEstimate,
    cloud_estimate: LearnedRouteEstimate,
    urgency: Urgency,
    policy: RoutingPolicy,
) -> bool:
    """Allow cloud to override a qualifying local route only on material advantage."""

    if local_estimate.quality_score < policy.minimum_quality_threshold:
        return True

    threshold = (
        policy.cloud_override_threshold_urgent
        if urgency == "urgent"
        else policy.cloud_override_threshold_normal
    )
    # The override threshold measures the material quality advantage of cloud.
    # Reliability is already accounted for in route cost; using max(success_rate,
    # quality_score) can erase a real quality gain when reliability is equal.
    local_outcome = local_estimate.quality_score
    cloud_outcome = cloud_estimate.quality_score
    if local_outcome <= 0.0:
        return cloud_outcome > 0.0

    expected_advantage = (cloud_outcome - local_outcome) / local_outcome
    return expected_advantage >= threshold


def effective_edge_cost(
    edge: GraphEdge,
    target: GraphNode,
    resources: ResourceState,
    estimate: LearnedRouteEstimate | None,
    policy: RoutingPolicy,
) -> float:
    """Calculate deterministic dimensionless cost for one graph transition."""

    weight = edge.weight
    cost = (
        policy.economic_weight * weight.economic_cost
        + policy.quota_weight * weight.quota_cost
        + policy.latency_weight * weight.latency_cost
        + policy.quality_weight * weight.quality_deficit
        + policy.privacy_weight * weight.privacy_penalty
        + policy.risk_weight * weight.operational_risk
        + policy.complexity_weight * weight.transition_complexity
    )

    if estimate is not None:
        cost += policy.retry_weight * estimate.retry_rate
        cost += policy.fallback_weight * estimate.fallback_rate
        cost += policy.quality_weight * (1.0 - estimate.success_rate)

    quota_fraction = resources.quota_fraction_remaining()
    if quota_fraction is not None and target.privacy_class != "local":
        cost += policy.quota_scarcity_weight * (1.0 - quota_fraction)

    budget_fraction = resources.budget_fraction_remaining()
    if budget_fraction is not None and target.privacy_class != "local":
        cost += policy.budget_scarcity_weight * (1.0 - budget_fraction)

    if target.privacy_class == "local":
        cost *= policy.local_preference_factor

    return max(float(cost), 0.0)
