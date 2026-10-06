from __future__ import annotations

from dataclasses import dataclass
import heapq
from itertools import count
from typing import Callable

from .errors import ContractValidationError
from .graph import GraphEdge, GraphSnapshot

Heuristic = Callable[[str, str, GraphSnapshot], float]
EdgeCost = Callable[[GraphEdge], float]


@dataclass(frozen=True)
class SearchResult:
    path: tuple[str, ...]
    edge_ids: tuple[str, ...]
    total_cost: float
    explored_nodes: int


def dijkstra(
    graph: GraphSnapshot,
    start: str,
    goal: str,
    *,
    max_explored_nodes: int = 10_000,
    edge_cost: EdgeCost | None = None,
) -> SearchResult:
    return _search(
        graph,
        start,
        goal,
        heuristic=lambda _node, _goal, _graph: 0.0,
        max_explored_nodes=max_explored_nodes,
        edge_cost=edge_cost,
    )


def astar(
    graph: GraphSnapshot,
    start: str,
    goal: str,
    *,
    heuristic: Heuristic,
    max_explored_nodes: int = 10_000,
    edge_cost: EdgeCost | None = None,
) -> SearchResult:
    """Run A* using a caller-supplied admissible heuristic."""
    return _search(
        graph,
        start,
        goal,
        heuristic=heuristic,
        max_explored_nodes=max_explored_nodes,
        edge_cost=edge_cost,
    )


def _search(
    graph: GraphSnapshot,
    start: str,
    goal: str,
    *,
    heuristic: Heuristic,
    max_explored_nodes: int,
    edge_cost: EdgeCost | None,
) -> SearchResult:
    _validate_endpoints(graph, start, goal)
    if max_explored_nodes < 1:
        raise ContractValidationError("max_explored_nodes must be >= 1")

    if start == goal:
        return SearchResult((start,), (), 0.0, 0)

    distances: dict[str, float] = {start: 0.0}
    paths: dict[str, tuple[str, ...]] = {start: (start,)}
    edge_paths: dict[str, tuple[str, ...]] = {start: ()}
    queue: list[tuple[float, float, tuple[str, ...], int, str]] = []
    sequence = count()

    start_h = _validated_heuristic(heuristic(start, goal, graph), start)
    heapq.heappush(queue, (start_h, 0.0, (start,), next(sequence), start))
    explored = 0

    while queue:
        _estimated_total, distance, path, _, node_id = heapq.heappop(queue)
        if distance != distances.get(node_id) or path != paths.get(node_id):
            continue

        explored += 1
        if explored > max_explored_nodes:
            raise ContractValidationError("graph search budget exhausted")
        if node_id == goal:
            return SearchResult(path, edge_paths[node_id], distance, explored)

        for edge in sorted(graph.outgoing(node_id), key=lambda item: item.edge_id):
            step_cost = edge.weight.total() if edge_cost is None else edge_cost(edge)
            if (
                step_cost != step_cost
                or step_cost in (float("inf"), float("-inf"))
                or step_cost < 0
            ):
                raise ContractValidationError(
                    f"edge cost for {edge.edge_id} must be finite and non-negative"
                )

            candidate_distance = distance + float(step_cost)
            candidate_path = path + (edge.target,)
            current_distance = distances.get(edge.target)
            current_path = paths.get(edge.target)
            if (
                current_distance is None
                or candidate_distance < current_distance
                or (
                    candidate_distance == current_distance
                    and candidate_path < current_path
                )
            ):
                distances[edge.target] = candidate_distance
                paths[edge.target] = candidate_path
                edge_paths[edge.target] = edge_paths[node_id] + (edge.edge_id,)
                h = _validated_heuristic(
                    heuristic(edge.target, goal, graph),
                    edge.target,
                )
                heapq.heappush(
                    queue,
                    (
                        candidate_distance + h,
                        candidate_distance,
                        candidate_path,
                        next(sequence),
                        edge.target,
                    ),
                )

    raise ContractValidationError("No route exists between start and goal")


def _validated_heuristic(value: float, node_id: str) -> float:
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        raise ContractValidationError(
            f"heuristic for {node_id} must be a finite non-negative number"
        )
    return float(value)


def _validate_endpoints(graph: GraphSnapshot, start: str, goal: str) -> None:
    known = {node.node_id for node in graph.nodes}
    if start not in known or goal not in known:
        raise ContractValidationError(
            "search start and goal must reference graph nodes"
        )
