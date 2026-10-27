from __future__ import annotations

from collections import deque
import math
from typing import Callable

from .errors import ContractValidationError
from .graph import GraphEdge, GraphSnapshot, TaskDemand

EdgeCost = Callable[[GraphEdge], float]


def admissible_lower_bound(
    graph: GraphSnapshot,
    node_id: str,
    goal_id: str,
    *,
    edge_cost: EdgeCost | None = None,
) -> float:
    """Return a conservative admissible lower bound for remaining graph cost."""

    known = {node.node_id for node in graph.nodes}
    if node_id not in known or goal_id not in known:
        raise ContractValidationError("heuristic endpoints must reference graph nodes")
    if node_id == goal_id:
        return 0.0

    costs = [
        edge.weight.total() if edge_cost is None else edge_cost(edge)
        for edge in graph.edges
        if edge.enabled
    ]
    if not costs:
        return 0.0
    if any(
        cost != cost or cost in (float("inf"), float("-inf")) or cost < 0
        for cost in costs
    ):
        raise ContractValidationError(
            "heuristic edge costs must be finite and non-negative"
        )

    minimum_edge_cost = min(costs)
    distances: dict[str, int] = {node_id: 0}
    queue: deque[str] = deque([node_id])

    while queue:
        current = queue.popleft()
        if current == goal_id:
            break
        for edge in sorted(graph.outgoing(current), key=lambda item: item.edge_id):
            if edge.target not in distances:
                distances[edge.target] = distances[current] + 1
                queue.append(edge.target)

    if goal_id not in distances:
        return 0.0

    bound = distances[goal_id] * minimum_edge_cost
    if not math.isfinite(bound) or bound < 0:
        raise ContractValidationError(
            "heuristic bound must be finite and non-negative"
        )
    return float(bound)


def build_admissible_heuristic(
    graph: GraphSnapshot,
    demand: TaskDemand,
    *,
    edge_cost: EdgeCost | None = None,
) -> Callable[[str, str, GraphSnapshot], float]:
    """Build the deterministic A* heuristic for a fixed routing contract.

    TaskDemand is accepted as part of the contract so future demand-derived
    lower bounds can be added only when their admissibility is proven.
    Version 1 intentionally ignores demand in the bound.
    """

    del demand
    return lambda node_id, goal_id, snapshot: admissible_lower_bound(
        snapshot,
        node_id,
        goal_id,
        edge_cost=edge_cost,
    )
