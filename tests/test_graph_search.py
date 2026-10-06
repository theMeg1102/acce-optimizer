from acce_optimizer.prototype.graph import EdgeWeight, GraphEdge, GraphNode, GraphSnapshot
from acce_optimizer.prototype.graph_search import astar, dijkstra
from acce_optimizer.prototype.heuristic import build_admissible_heuristic


def make_graph():
    nodes = tuple(
        GraphNode(node_id, "provider", None, (), 4096, "local", True, True)
        for node_id in ("start", "local", "cloud", "goal")
    )
    edges = (
        GraphEdge("e1", "start", "local", "execute", EdgeWeight(economic_cost=1)),
        GraphEdge("e2", "local", "goal", "terminate", EdgeWeight(economic_cost=1)),
        GraphEdge("e3", "start", "cloud", "execute", EdgeWeight(economic_cost=4)),
        GraphEdge("e4", "cloud", "goal", "terminate", EdgeWeight(economic_cost=1)),
    )
    return GraphSnapshot("g1", "1", nodes, edges, "p1", "t1")


def test_dijkstra_and_astar_select_same_minimum_cost_path():
    graph = make_graph()
    d = dijkstra(graph, "start", "goal")
    heuristic = build_admissible_heuristic(
        graph,
        __import__("acce_optimizer.prototype.graph", fromlist=["TaskDemand"]).TaskDemand(
            0.1, 0.1, 0.1, 100, 0.1, 0.1, 0.1, 0.1, 0.5
        ),
    )
    a = astar(graph, "start", "goal", heuristic=heuristic)

    assert d.path == ("start", "local", "goal")
    assert a.path == d.path
    assert a.total_cost == d.total_cost == 2.0
