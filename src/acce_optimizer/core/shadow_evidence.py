from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ShadowEvidenceSummary:
    """Deterministic aggregate of minimized adaptive-shadow evidence."""

    sample_count: int
    agreement_count: int
    divergence_count: int
    agreement_rate: float
    divergence_rate: float
    cloud_divergence_count: int
    local_divergence_count: int
    counterfactual_cloud_quota_preserved_count: int
    counterfactual_cloud_quota_preserved_rate: float
    divergence_classes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "agreement_count": self.agreement_count,
            "divergence_count": self.divergence_count,
            "agreement_rate": self.agreement_rate,
            "divergence_rate": self.divergence_rate,
            "cloud_divergence_count": self.cloud_divergence_count,
            "local_divergence_count": self.local_divergence_count,
            "counterfactual_cloud_quota_preserved_count": (
                self.counterfactual_cloud_quota_preserved_count
            ),
            "counterfactual_cloud_quota_preserved_rate": (
                self.counterfactual_cloud_quota_preserved_rate
            ),
            "divergence_classes": list(self.divergence_classes),
        }


def summarize_shadow_evidence(
    results: Iterable[dict[str, Any]],
) -> ShadowEvidenceSummary:
    """Aggregate shadow comparisons without executing models or mutating state.

    A cloud-to-local divergence is treated as a counterfactual cloud-quota
    preservation opportunity. This is intentionally a counterfactual metric:
    no realized quota savings are claimed by shadow mode.
    """

    records = tuple(results)
    sample_count = len(records)
    agreement_count = sum(bool(item.get("route_agreement")) for item in records)
    divergence_count = sample_count - agreement_count

    cloud_divergence_count = 0
    local_divergence_count = 0
    preserved_count = 0
    classes: set[str] = set()

    for item in records:
        if item.get("route_agreement"):
            classes.add("agreement")
            continue

        production_resource = item.get("production_resource_type")
        adaptive_resource = item.get("adaptive_resource_type")

        if production_resource == "cloud_model" and adaptive_resource != "cloud_model":
            cloud_divergence_count += 1
            preserved_count += 1
            classes.add("cloud_to_local")
        elif production_resource != "cloud_model" and adaptive_resource == "cloud_model":
            local_divergence_count += 1
            classes.add("local_to_cloud")
        else:
            classes.add("route_change")

    return ShadowEvidenceSummary(
        sample_count=sample_count,
        agreement_count=agreement_count,
        divergence_count=divergence_count,
        agreement_rate=agreement_count / sample_count if sample_count else 1.0,
        divergence_rate=divergence_count / sample_count if sample_count else 0.0,
        cloud_divergence_count=cloud_divergence_count,
        local_divergence_count=local_divergence_count,
        counterfactual_cloud_quota_preserved_count=preserved_count,
        counterfactual_cloud_quota_preserved_rate=(
            preserved_count / sample_count if sample_count else 0.0
        ),
        divergence_classes=tuple(sorted(classes)),
    )
