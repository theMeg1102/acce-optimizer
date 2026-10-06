from __future__ import annotations

import unittest

from acce_optimizer.prototype.shadow_evidence import summarize_shadow_evidence


class ShadowEvidenceTest(unittest.TestCase):
    def test_empty_corpus_is_deterministic_and_safe(self) -> None:
        summary = summarize_shadow_evidence(())

        self.assertEqual(summary.sample_count, 0)
        self.assertEqual(summary.agreement_count, 0)
        self.assertEqual(summary.divergence_count, 0)
        self.assertEqual(summary.agreement_rate, 1.0)
        self.assertEqual(summary.divergence_rate, 0.0)
        self.assertEqual(summary.counterfactual_cloud_quota_preserved_rate, 0.0)

    def test_aggregates_agreement_divergence_and_quota_preservation(self) -> None:
        summary = summarize_shadow_evidence(
            (
                {
                    "route_agreement": True,
                    "production_resource_type": "deterministic_tool",
                    "adaptive_resource_type": "deterministic_tool",
                },
                {
                    "route_agreement": False,
                    "production_resource_type": "cloud_model",
                    "adaptive_resource_type": "deterministic_tool",
                },
                {
                    "route_agreement": False,
                    "production_resource_type": "deterministic_tool",
                    "adaptive_resource_type": "cloud_model",
                },
            )
        )

        self.assertEqual(summary.sample_count, 3)
        self.assertEqual(summary.agreement_count, 1)
        self.assertEqual(summary.divergence_count, 2)
        self.assertAlmostEqual(summary.agreement_rate, 1 / 3)
        self.assertAlmostEqual(summary.divergence_rate, 2 / 3)
        self.assertEqual(summary.cloud_divergence_count, 1)
        self.assertEqual(summary.local_divergence_count, 1)
        self.assertEqual(summary.counterfactual_cloud_quota_preserved_count, 1)
        self.assertAlmostEqual(
            summary.counterfactual_cloud_quota_preserved_rate,
            1 / 3,
        )
        self.assertEqual(
            summary.divergence_classes,
            ("agreement", "cloud_to_local", "local_to_cloud"),
        )

    def test_as_dict_is_json_friendly(self) -> None:
        summary = summarize_shadow_evidence(
            (
                {
                    "route_agreement": False,
                    "production_resource_type": "cloud_model",
                    "adaptive_resource_type": "deterministic_tool",
                },
            )
        )

        payload = summary.as_dict()

        self.assertEqual(payload["sample_count"], 1)
        self.assertEqual(payload["divergence_classes"], ["cloud_to_local"])
        self.assertEqual(payload["counterfactual_cloud_quota_preserved_count"], 1)


if __name__ == "__main__":
    unittest.main()
