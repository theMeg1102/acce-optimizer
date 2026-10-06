from __future__ import annotations

import json
from pathlib import Path
import unittest

from acce_optimizer.prototype.models import DecisionRequest
from acce_optimizer.prototype.registry import CapabilityRegistry
from acce_optimizer.prototype.routing_policy import RoutingPolicy
from acce_optimizer.prototype.runtime import DecisionService


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "fixtures/registry/sprint_003_registry.json"
REQUEST = ROOT / "fixtures/requests/sprint_003_multiple_routes_request.json"


class AdaptiveShadowIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DecisionService.from_paths(REGISTRY)
        self.request_data = json.loads(REQUEST.read_text(encoding="utf-8"))

    def test_shadow_agrees_without_changing_production_selection(self) -> None:
        request = DecisionRequest.from_mapping(self.request_data)
        production = self.service.decide(request)
        shadow = self.service.shadow_adaptive_decision(request)

        self.assertEqual(production["selected_route"]["route_id"], "route.local.v1.fast_confident")
        self.assertEqual(shadow["production_route_id"], production["selected_route"]["route_id"])
        self.assertEqual(shadow["adaptive_route_id"], production["selected_route"]["route_id"])
        self.assertTrue(shadow["route_agreement"])
        self.assertFalse(shadow["routing_applied"])
        self.assertTrue(shadow["production_selection_unchanged"])
        self.assertFalse(shadow["runtime_state_mutated"])
        self.assertFalse(shadow["model_execution_requested"])
        self.assertFalse(shadow["conversation_content_recorded"])

    def test_shadow_can_intentionally_diverge_under_explicit_adaptive_policy(self) -> None:
        data = json.loads(json.dumps(self.request_data))
        data["task_class"] = "fallback_demo"
        data["summary"] = "Evaluate the fallback route under an explicit adaptive policy."
        data["constraints"]["external_network_allowed"] = True
        data["constraints"]["privacy_level"] = "restricted_external"
        data["governance"]["approval_required"] = True
        data["governance"]["approval_granted"] = True

        request = DecisionRequest.from_mapping(data)
        production = self.service.decide(request)
        shadow = self.service.shadow_adaptive_decision(
            request,
            policy=RoutingPolicy(
                minimum_quality_threshold=0.6,
                economic_weight=0.0,
                quota_weight=0.0,
                latency_weight=0.0,
                quality_weight=10.0,
                retry_weight=0.0,
                fallback_weight=0.0,
                privacy_weight=0.0,
                risk_weight=0.0,
                complexity_weight=0.0,
                local_preference_factor=1.0,
                quota_scarcity_weight=0.0,
                budget_scarcity_weight=0.0,
                cloud_override_threshold_normal=0.0,
            ),
        )

        self.assertEqual(production["selected_route"]["route_id"], "route.local.v1.fallback")
        self.assertEqual(shadow["production_route_id"], "route.local.v1.fallback")
        self.assertEqual(shadow["adaptive_route_id"], "route.cloud.v1.preferred")
        self.assertFalse(shadow["route_agreement"])
        self.assertFalse(shadow["routing_applied"])
        self.assertTrue(shadow["production_selection_unchanged"])

    def test_shadow_uses_immutable_registry_snapshot(self) -> None:
        registry = CapabilityRegistry(json.loads(REGISTRY.read_text(encoding="utf-8")))
        request = DecisionRequest.from_mapping(self.request_data)
        before = registry.snapshot

        service = DecisionService(registry)
        service.shadow_adaptive_decision(request)

        self.assertEqual(registry.snapshot, before)


if __name__ == "__main__":
    unittest.main()
