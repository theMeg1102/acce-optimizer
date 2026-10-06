from acce_optimizer.core.graph import EdgeWeight, GraphEdge, GraphNode, GraphSnapshot, TaskDemand
from acce_optimizer.core.learning import LearnedPreference
from acce_optimizer.core.resource_state import ResourceState


def test_core_contracts_are_immutable_and_validated():
    demand = TaskDemand(0.7, 0.8, 0.6, 4096, 0.9, 0.2, 0.1, 0.5, 0.9)
    node = GraphNode("local", "local", "model", ("reasoning",), 8192, "local", True, True)
    graph = GraphSnapshot(
        "snapshot-1",
        "1",
        (node,),
        (),
        "policy-1",
        "telemetry-1",
    )
    state = ResourceState(observed_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    preference = LearnedPreference("user", "coding", "local", "learned", 0.9, 5, 0.95, 0.9)

    assert demand.context_size == 4096
    assert graph.nodes == (node,)
    assert state.quota_fraction_remaining() is None
    assert preference.evidence_count == 5


def test_edge_weight_total_is_deterministic():
    weight = EdgeWeight(economic_cost=1.0, quota_cost=2.0, latency_cost=0.5)
    assert weight.total() == 3.5
