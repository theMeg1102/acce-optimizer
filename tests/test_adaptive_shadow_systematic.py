from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import unittest

from acce_optimizer.prototype.models import DecisionRequest
from acce_optimizer.prototype.registry import CapabilityRegistry
from acce_optimizer.prototype.routing_policy import RoutingPolicy
from acce_optimizer.prototype.runtime import DecisionService, EconomicPolicy, QuotaPolicy


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "fixtures/registry/sprint_003_registry.json"
REQUEST = ROOT / "fixtures/requests/sprint_003_multiple_routes_request.json"


class AdaptiveShadowSystematicTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry_data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.request_data = json.loads(REQUEST.read_text(encoding="utf-8"))

    def _service(
        self,
        *,
        quota: float = 1.0,
        budget: float = 20.0,
        spend: float = 0.0,
    ) -> DecisionService:
        return DecisionService(
            CapabilityRegistry(deepcopy(self.registry_data)),
            economic_policy=EconomicPolicy(
                monthly_cloud_budget_usd=budget,
                monthly_cloud_spend_usd=spend,
                cloud_quota_remaining_fraction=quota,
            ),
            quota_policy=QuotaPolicy(remaining_fraction=quota),
        )

    def _request(self, **changes: object) -> DecisionRequest:
        data = deepcopy(self.request_data)
        for key, value in changes.items():
            if key == "constraints":
                data["constraints"].update(value)
            elif key == "governance":
                data["governance"].update(value)
            else:
                data[key] = value
        return DecisionRequest.from_mapping(data)

    def _cloud_override_policy(self) -> RoutingPolicy:
        return RoutingPolicy(
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
            cloud_override_threshold_normal=0.0,
            cloud_override_threshold_urgent=0.0,
        )

    def test_shadow_corpus_reports_agreement_and_controlled_divergence(self) -> None:
        service = self._service()
        scenarios = (
            ("baseline", self._request(), RoutingPolicy()),
            (
                "explicit_cloud_quality_policy",
                self._request(
                    task_class="fallback_demo",
                    summary="Evaluate the fallback route under an explicit adaptive policy.",
                    constraints={"external_network_allowed": True, "privacy_level": "restricted_external"},
                    governance={"approval_required": True, "approval_granted": True},
                ),
                self._cloud_override_policy(),
            ),
        )

        results = [
            service.shadow_adaptive_decision(request, policy=policy)
            for _, request, policy in scenarios
        ]

        agreement_count = sum(result["route_agreement"] for result in results)
        divergence_count = len(results) - agreement_count
        cloud_divergence_count = sum(
            not result["route_agreement"] and result["adaptive_route_id"] == "route.cloud.v1.preferred"
            for result in results
        )

        self.assertGreaterEqual(agreement_count, 1)
        self.assertEqual(divergence_count, 1)
        self.assertEqual(cloud_divergence_count, 1)
        self.assertTrue(all(not result["routing_applied"] for result in results))
        self.assertTrue(all(result["production_selection_unchanged"] for result in results))

    def test_normal_cloud_advantage_below_default_threshold_does_not_override_local(self) -> None:
        service = self._service()
        request = self._request(
            task_class="fallback_demo",
            summary="Compare local and cloud quality under normal urgency.",
            constraints={"external_network_allowed": True, "privacy_level": "restricted_external"},
            governance={"approval_required": True, "approval_granted": True},
        )

        shadow = service.shadow_adaptive_decision(request)

        self.assertEqual(shadow["production_route_id"], "route.local.v1.fallback")
        self.assertEqual(shadow["adaptive_route_id"], "route.local.v1.fallback")
        self.assertTrue(shadow["route_agreement"])

    def test_cloud_resource_scarcity_changes_adaptive_cost_without_mutating_runtime(self) -> None:
        request = self._request(
            task_class="fallback_demo",
            summary="Compare cloud resource scarcity for an explicit adaptive route.",
            constraints={"external_network_allowed": True, "privacy_level": "restricted_external"},
            governance={"approval_required": True, "approval_granted": True},
        )
        policy = self._cloud_override_policy()

        abundant = self._service(quota=1.0, budget=20.0)
        scarce = self._service(quota=0.05, budget=1.0, spend=0.95)

        abundant_before = abundant.runtime_snapshot
        scarce_before = scarce.runtime_snapshot

        abundant_shadow = abundant.shadow_adaptive_decision(request, policy=policy)
        scarce_shadow = scarce.shadow_adaptive_decision(request, policy=policy)

        self.assertEqual(abundant_shadow["adaptive_route_id"], "route.cloud.v1.preferred")
        self.assertEqual(scarce_shadow["adaptive_route_id"], "route.local.v1.fallback")
        self.assertGreater(
            scarce_shadow["adaptive_total_cost"],
            abundant_shadow["adaptive_total_cost"],
        )
        self.assertEqual(abundant.runtime_snapshot, abundant_before)
        self.assertEqual(scarce.runtime_snapshot, scarce_before)
        self.assertFalse(scarce_shadow["runtime_state_mutated"])

    def test_hard_governance_removes_cloud_before_search(self) -> None:
        service = self._service()
        request = self._request(
            task_class="fallback_demo",
            summary="Cloud route is blocked by external network policy.",
            constraints={"external_network_allowed": False, "privacy_level": "internal"},
            governance={"approval_required": True, "approval_granted": True},
        )

        shadow = service.shadow_adaptive_decision(request, policy=self._cloud_override_policy())

        self.assertEqual(shadow["adaptive_route_id"], "route.local.v1.fallback")
        self.assertEqual(shadow["adaptive_governed_route_count"], 1)
        self.assertTrue(shadow["production_selection_unchanged"])

    def test_no_adaptive_route_is_reported_without_execution(self) -> None:
        service = self._service()
        request = self._request(
            constraints={"min_quality_score": 1.0},
        )

        shadow = service.shadow_adaptive_decision(request)

        self.assertEqual(shadow["adaptive_status"], "no_adaptive_route")
        self.assertIsNone(shadow["adaptive_route_id"])
        self.assertFalse(shadow["routing_applied"])
        self.assertFalse(shadow["model_execution_requested"])
        self.assertFalse(shadow["conversation_content_recorded"])

    def test_repeated_shadow_evaluation_is_deterministic(self) -> None:
        service = self._service()
        request = self._request()

        first = service.shadow_adaptive_decision(request)
        second = service.shadow_adaptive_decision(request)

        stable_fields = (
            "production_route_id",
            "adaptive_route_id",
            "adaptive_status",
            "route_agreement",
            "adaptive_algorithm",
            "adaptive_candidate_count",
            "adaptive_governed_route_count",
            "routing_applied",
            "production_selection_unchanged",
            "runtime_state_mutated",
            "model_execution_requested",
            "conversation_content_recorded",
        )
        self.assertEqual(
            {field: first[field] for field in stable_fields},
            {field: second[field] for field in stable_fields},
        )
        self.assertEqual(first["adaptive_total_cost"], second["adaptive_total_cost"])

    def test_shadow_does_not_mutate_registry_snapshot(self) -> None:
        registry = CapabilityRegistry(deepcopy(self.registry_data))
        service = DecisionService(registry)
        before = registry.snapshot

        service.shadow_adaptive_decision(self._request())

        self.assertEqual(registry.snapshot, before)


if __name__ == "__main__":
    unittest.main()
