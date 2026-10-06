from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .errors import ContractValidationError
from .execution_graph import build_execution_graph, search_execution_graph, task_demand_from_request
from .models import DecisionRequest
from .registry import CapabilityRegistry
from .resource_state import ResourceState
from .routing_policy import RoutingPolicy


def adaptive_shadow_compare(
    request: DecisionRequest,
    authoritative_plan: dict[str, Any],
    registry: CapabilityRegistry,
    *,
    economic_policy: Any,
    quota_policy: Any,
    policy: RoutingPolicy | None = None,
) -> dict[str, Any]:
    """Evaluate adaptive graph routing without changing the production decision.

    The authoritative plan remains the reference decision. This function only constructs an
    immutable adaptive graph, searches it, and returns minimized comparison
    metadata. No provider/model execution or runtime mutation occurs.
    """

    routing_policy = policy or RoutingPolicy(
        minimum_quality_threshold=request.min_quality_score,
    )
    resources = ResourceState(
        observed_at=datetime.now(timezone.utc),
        quota_remaining=quota_policy.remaining_fraction,
        quota_limit=1.0,
        budget_remaining=max(
            economic_policy.monthly_cloud_budget_usd
            - economic_policy.monthly_cloud_spend_usd,
            0.0,
        ),
        budget_limit=economic_policy.monthly_cloud_budget_usd,
    )

    candidates: list[Any] = []
    seen_route_ids: set[str] = set()
    for capability_id in request.required_capabilities:
        for route in registry.candidates_for(capability_id):
            if route.route_id not in seen_route_ids:
                candidates.append(route)
                seen_route_ids.add(route.route_id)

    route_by_id = {route.route_id: route for route in candidates}

    graph = build_execution_graph(
        request,
        tuple(candidates),
        resources,
        routing_policy,
    )
    adaptive_route_id: str | None = None
    adaptive_cost: float | None = None
    explored_nodes = 0
    adaptive_status = "route_selected"

    if graph.route_by_node:
        try:
            result = search_execution_graph(
                graph,
                task_demand_from_request(request),
                resources,
                routing_policy,
                algorithm="astar",
                max_explored_nodes=max(request.search_budget_max_candidate_routes, 1),
            )
            adaptive_route_id = result.selected_route.route_id
            adaptive_cost = result.search.total_cost
            explored_nodes = result.search.explored_nodes
        except ContractValidationError:
            adaptive_status = "no_adaptive_route"
    else:
        adaptive_status = "no_adaptive_route"

    production_route = authoritative_plan.get("selected_route")
    production_route_id = (
        production_route.get("route_id")
        if isinstance(production_route, dict)
        else None
    )

    production_resource_type = None
    if production_route_id in route_by_id:
        production_resource_type = route_by_id[production_route_id].resource_type
    elif isinstance(production_route, dict):
        production_resource_type = production_route.get("resource_type")

    adaptive_resource_type = None
    if adaptive_route_id in route_by_id:
        adaptive_resource_type = route_by_id[adaptive_route_id].resource_type

    if production_route_id == adaptive_route_id:
        divergence_class = "agreement"
    elif production_resource_type == "cloud_model" and adaptive_resource_type != "cloud_model":
        divergence_class = "cloud_to_local"
    elif production_resource_type != "cloud_model" and adaptive_resource_type == "cloud_model":
        divergence_class = "local_to_cloud"
    elif adaptive_status == "no_adaptive_route":
        divergence_class = "no_adaptive_route"
    else:
        divergence_class = "route_change"

    return {
        "schema_version": "1.1",
        "status": "shadow_evaluated",
        "request_id": request.request_id,
        "production_decision_id": authoritative_plan.get("decision_id"),
        "production_route_id": production_route_id,
        "production_resource_type": production_resource_type,
        "adaptive_route_id": adaptive_route_id,
        "adaptive_resource_type": adaptive_resource_type,
        "adaptive_status": adaptive_status,
        "divergence_class": divergence_class,
        "route_agreement": production_route_id == adaptive_route_id,
        "adaptive_algorithm": "astar",
        "adaptive_total_cost": adaptive_cost,
        "adaptive_explored_nodes": explored_nodes,
        "adaptive_graph_snapshot_id": graph.snapshot.snapshot_id,
        "adaptive_candidate_count": len(candidates),
        "adaptive_governed_route_count": len(graph.route_by_node),
        "routing_applied": False,
        "production_selection_unchanged": True,
        "runtime_state_mutated": False,
        "model_execution_requested": False,
        "conversation_content_recorded": False,
    }
