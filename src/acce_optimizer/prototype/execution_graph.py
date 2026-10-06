from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Mapping

from .graph import EdgeWeight, GraphEdge, GraphNode, GraphSnapshot, TaskDemand
from .graph_search import SearchResult, astar, dijkstra
from .learning import LearnedRouteEstimate
from .models import CandidateRoute, DecisionRequest
from .resource_state import ResourceState
from .engine import route_blocking_reason
from .routing_policy import (
    RoutingPolicy,
    cloud_override_allowed,
    effective_edge_cost,
    route_is_governed,
)


START_NODE = "__acce_start__"
GOAL_NODE = "__acce_goal__"


@dataclass(frozen=True)
class ExecutionGraph:
    """Graph plus deterministic route metadata for one ACCE decision."""

    snapshot: GraphSnapshot
    start_node: str
    goal_node: str
    route_by_node: Mapping[str, CandidateRoute]
    estimate_by_node: Mapping[str, LearnedRouteEstimate]


@dataclass(frozen=True)
class AdaptiveSearchResult:
    """Search result with the selected ACCE candidate route."""

    search: SearchResult
    selected_route: CandidateRoute


def task_demand_from_request(request: DecisionRequest) -> TaskDemand:
    """Derive a transparent, deterministic demand vector from the request.

    This is intentionally rule-based in the first integration step. It does
    not call a model and therefore cannot change routing through hidden LLM
    reasoning. A future measured classifier may replace this function behind
    the same contract.
    """

    text = f"{request.task_class} {request.summary} {' '.join(request.required_capabilities)}".lower()

    def has(*terms: str) -> bool:
        return any(term in text for term in terms)

    reasoning = 0.8 if has("reason", "analysis", "architecture", "debug", "design") else 0.5
    coding = 0.9 if has("code", "coding", "program", "python", "typescript", "javascript", "sql") else 0.2
    complexity = 0.8 if has("architecture", "design", "debug", "complex", "multi-step") else 0.5
    precision = 0.9 if has("exact", "precision", "audit", "financial", "compliance") else 0.6
    tool_dependency = 0.8 if request.tools_allowed is not False else 0.0
    privacy = 1.0 if request.privacy_level in {"restricted", "confidential"} else 0.7
    latency = 0.9 if request.urgency == "urgent" else 0.5

    return TaskDemand(
        complexity=complexity,
        reasoning=reasoning,
        coding=coding,
        context_size=request.context_current_tokens
        + request.context_estimated_input_tokens
        + request.context_expected_output_tokens,
        precision_required=precision,
        tool_dependency=tool_dependency,
        privacy_requirement=privacy,
        latency_sensitivity=latency,
        quality_requirement=max(request.min_quality_score, 0.0),
    )


def build_execution_graph(
    request: DecisionRequest,
    routes: tuple[CandidateRoute, ...] | list[CandidateRoute],
    resources: ResourceState,
    policy: RoutingPolicy,
    estimates: Mapping[str, LearnedRouteEstimate] | None = None,
) -> ExecutionGraph:
    """Build an immutable executable graph after hard governance."""

    estimates = estimates or {}
    if request.min_quality_score > policy.minimum_quality_threshold:
        policy = replace(
            policy,
            minimum_quality_threshold=request.min_quality_score,
        )
    route_by_node: dict[str, CandidateRoute] = {}
    estimate_by_node: dict[str, LearnedRouteEstimate] = {}
    nodes: list[GraphNode] = [
        GraphNode(
            START_NODE,
            "acce",
            None,
            ("start",),
            max(request.context_hard_limit_tokens, 1),
            "local",
            True,
            True,
        ),
        GraphNode(
            GOAL_NODE,
            "acce",
            None,
            ("terminate",),
            max(request.context_hard_limit_tokens, 1),
            "local",
            True,
            True,
        ),
    ]
    edges: list[GraphEdge] = []

    candidates = tuple(routes)
    for route in candidates:
        estimate = estimates.get(route.route_id) or _estimate_from_route(route)
        node_id = f"route:{route.route_id}"
        node = GraphNode(
            node_id=node_id,
            provider_id=route.provider_id,
            model_id=route.model_used,
            capabilities=route.supported_task_classes,
            context_limit=route.context_window_tokens or request.context_hard_limit_tokens,
            privacy_class="local" if route.resource_type != "cloud_model" else "external",
            authorized=True,
            available=route.availability == "available",
        )

        if not route_is_governed(node, estimate, policy):
            continue
        if route_blocking_reason(request, route) is not None:
            continue

        route_by_node[node_id] = route
        estimate_by_node[node_id] = estimate
        nodes.append(node)

    local_nodes = [
        node_id
        for node_id, route in route_by_node.items()
        if route.resource_type != "cloud_model"
    ]
    governed_local = [
        node_id
        for node_id in local_nodes
        if estimate_by_node[node_id].quality_score >= policy.minimum_quality_threshold
    ]

    for node_id, route in sorted(route_by_node.items()):
        estimate = estimate_by_node[node_id]
        target = next(node for node in nodes if node.node_id == node_id)

        if route.resource_type == "cloud_model" and governed_local:
            best_local = max(
                (estimate_by_node[item] for item in governed_local),
                key=lambda item: (item.quality_score, item.success_rate),
            )
            if not cloud_override_allowed(
                local_estimate=best_local,
                cloud_estimate=estimate,
                urgency=request.urgency,
                policy=policy,
            ):
                continue

        edges.append(
            GraphEdge(
                edge_id=f"select:{route.route_id}",
                source=START_NODE,
                target=node_id,
                transition="execute",
                weight=_edge_weight(route, request),
                learned=route.route_id in estimates,
            )
        )
        edges.append(
            GraphEdge(
                edge_id=f"terminate:{route.route_id}",
                source=node_id,
                target=GOAL_NODE,
                transition="terminate",
                weight=EdgeWeight(),
                learned=False,
            )
        )

    snapshot = GraphSnapshot(
        snapshot_id=f"adaptive:{request.request_id}",
        version="1",
        nodes=tuple(nodes),
        edges=tuple(edges),
        policy_version="routing-policy-v1",
        telemetry_version="resource-state-v1",
    )
    return ExecutionGraph(
        snapshot=snapshot,
        start_node=START_NODE,
        goal_node=GOAL_NODE,
        route_by_node=route_by_node,
        estimate_by_node=estimate_by_node,
    )


def search_execution_graph(
    graph: ExecutionGraph,
    demand: TaskDemand,
    resources: ResourceState,
    policy: RoutingPolicy,
    *,
    algorithm: str = "astar",
    max_explored_nodes: int = 10_000,
) -> AdaptiveSearchResult:
    """Optimize the governed graph with deterministic dynamic edge costs."""

    def edge_cost(edge: GraphEdge) -> float:
        target = next(node for node in graph.snapshot.nodes if node.node_id == edge.target)
        estimate = graph.estimate_by_node.get(edge.target)
        return effective_edge_cost(edge, target, resources, estimate, policy)

    if algorithm == "dijkstra":
        result = dijkstra(
            graph.snapshot,
            graph.start_node,
            graph.goal_node,
            max_explored_nodes=max_explored_nodes,
            edge_cost=edge_cost,
        )
    elif algorithm == "astar":
        from .heuristic import build_admissible_heuristic

        heuristic = build_admissible_heuristic(
            graph.snapshot,
            demand,
            edge_cost=edge_cost,
        )
        result = astar(
            graph.snapshot,
            graph.start_node,
            graph.goal_node,
            heuristic=heuristic,
            max_explored_nodes=max_explored_nodes,
            edge_cost=edge_cost,
        )
    else:
        raise ValueError(f"unsupported search algorithm: {algorithm}")

    selected_node = next(
        node_id for node_id in reversed(result.path) if node_id in graph.route_by_node
    )
    return AdaptiveSearchResult(result, graph.route_by_node[selected_node])


def _estimate_from_route(route: CandidateRoute) -> LearnedRouteEstimate:
    return LearnedRouteEstimate(
        route_id=route.route_id,
        sample_count=0,
        confidence=0.0,
        success_rate=route.quality_score,
        quality_score=route.quality_score,
        latency_p50=float(route.estimated_latency_ms),
        latency_p95=float(route.estimated_latency_ms),
        context_growth=0.0,
        quota_consumption=1.0 if route.quota_metered else 0.0,
        fallback_rate=0.0,
        retry_rate=0.0,
        user_acceptance=None,
    )


def _edge_weight(route: CandidateRoute, request: DecisionRequest) -> EdgeWeight:
    latency = route.estimated_latency_ms / max(request.max_latency_ms, 1)
    quota = 1.0 if route.quota_metered else 0.0
    economic = route.estimated_cloud_cost_usd if route.monetary_metered else 0.0
    return EdgeWeight(
        economic_cost=economic,
        quota_cost=quota,
        latency_cost=min(latency, 1.0),
        quality_deficit=max(0.0, 1.0 - route.quality_score),
        privacy_penalty=route.privacy_penalty,
        operational_risk=route.risk_score,
        transition_complexity=route.complexity_score,
    )
