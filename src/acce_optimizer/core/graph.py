from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .errors import ContractValidationError

SearchAlgorithm = Literal["dijkstra", "astar"]


def _finite_non_negative(value: float, field: str) -> float:
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        raise ContractValidationError(f"{field} must be a finite non-negative number")
    return float(value)


@dataclass(frozen=True)
class TaskDemand:
    """Normalized routing demand independent of the selected model."""

    complexity: float
    reasoning: float
    coding: float
    context_size: int
    precision_required: float
    tool_dependency: float
    privacy_requirement: float
    latency_sensitivity: float
    quality_requirement: float

    def __post_init__(self) -> None:
        for field in (
            "complexity",
            "reasoning",
            "coding",
            "precision_required",
            "tool_dependency",
            "privacy_requirement",
            "latency_sensitivity",
            "quality_requirement",
        ):
            value = getattr(self, field)
            if not 0.0 <= value <= 1.0:
                raise ContractValidationError(f"{field} must be between 0 and 1")
        if self.context_size < 0:
            raise ContractValidationError("context_size must be non-negative")


@dataclass(frozen=True)
class GraphNode:
    """Executable model endpoint or explicit execution state."""

    node_id: str
    provider_id: str
    model_id: str | None
    capabilities: tuple[str, ...]
    context_limit: int
    privacy_class: str
    authorized: bool
    available: bool

    def __post_init__(self) -> None:
        if not self.node_id.strip():
            raise ContractValidationError("node_id must be non-empty")
        if not self.provider_id.strip():
            raise ContractValidationError("provider_id must be non-empty")
        if self.context_limit < 1:
            raise ContractValidationError("context_limit must be >= 1")


@dataclass(frozen=True)
class EdgeWeight:
    """Versioned learned/estimated components used by the optimizer."""

    economic_cost: float = 0.0
    quota_cost: float = 0.0
    latency_cost: float = 0.0
    quality_deficit: float = 0.0
    context_growth: float = 0.0
    retry_cost: float = 0.0
    fallback_cost: float = 0.0
    privacy_penalty: float = 0.0
    operational_risk: float = 0.0
    transition_complexity: float = 0.0

    def __post_init__(self) -> None:
        for field in self.__dataclass_fields__:
            _finite_non_negative(getattr(self, field), field)

    def total(self) -> float:
        return sum(getattr(self, field) for field in self.__dataclass_fields__)


@dataclass(frozen=True)
class GraphEdge:
    """A directed, valid transition between execution states."""

    edge_id: str
    source: str
    target: str
    transition: str
    weight: EdgeWeight
    enabled: bool = True
    learned: bool = False

    def __post_init__(self) -> None:
        if not self.edge_id.strip():
            raise ContractValidationError("edge_id must be non-empty")
        if not self.source.strip() or not self.target.strip():
            raise ContractValidationError("edge source and target must be non-empty")
        if not self.transition.strip():
            raise ContractValidationError("edge transition must be non-empty")
        if self.source == self.target and self.transition != "terminate":
            raise ContractValidationError("self-loop edges are only valid for terminate transitions")


@dataclass(frozen=True)
class GraphSnapshot:
    """Immutable graph state consumed by a single routing decision."""

    snapshot_id: str
    version: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    policy_version: str
    telemetry_version: str

    def __post_init__(self) -> None:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ContractValidationError("graph node IDs must be unique")
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ContractValidationError("graph edge IDs must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ContractValidationError(
                    f"edge {edge.edge_id} references an unknown node"
                )

    def outgoing(self, node_id: str) -> tuple[GraphEdge, ...]:
        return tuple(edge for edge in self.edges if edge.enabled and edge.source == node_id)


@dataclass(frozen=True)
class RoutingDecision:
    """Auditable result of one graph search."""

    decision_id: str
    snapshot_id: str
    algorithm: SearchAlgorithm
    demand: TaskDemand
    path: tuple[str, ...]
    total_cost: float
    heuristic_cost: float
    search_budget: int
    explored_nodes: int
    governance_passed: bool

    def __post_init__(self) -> None:
        if not self.decision_id.strip():
            raise ContractValidationError("decision_id must be non-empty")
        if not self.snapshot_id.strip():
            raise ContractValidationError("snapshot_id must be non-empty")
        if self.total_cost < 0 or self.heuristic_cost < 0:
            raise ContractValidationError("routing costs must be non-negative")
        if self.search_budget < 1:
            raise ContractValidationError("search_budget must be >= 1")
        if self.explored_nodes < 0:
            raise ContractValidationError("explored_nodes must be non-negative")
        if not self.path:
            raise ContractValidationError("routing decision path must not be empty")

    @property
    def selected_node(self) -> str:
        return self.path[-1]