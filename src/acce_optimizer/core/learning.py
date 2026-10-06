from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .errors import ContractValidationError


def _finite_non_negative(value: float, field: str) -> float:
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        raise ContractValidationError(f"{field} must be a finite non-negative number")
    return float(value)


@dataclass(frozen=True)
class LearnedRouteEstimate:
    """Evidence-backed estimate used to update future graph snapshots."""

    route_id: str
    sample_count: int
    confidence: float
    success_rate: float
    quality_score: float
    latency_p50: float
    latency_p95: float
    context_growth: float
    quota_consumption: float
    fallback_rate: float
    retry_rate: float
    user_acceptance: float | None = None
    preferred_by_user: bool | None = None

    def __post_init__(self) -> None:
        if not self.route_id.strip():
            raise ContractValidationError("route_id must be non-empty")
        if self.sample_count < 0:
            raise ContractValidationError("sample_count must be >= 0")
        for field in ("confidence", "success_rate", "quality_score", "fallback_rate", "retry_rate"):
            value = getattr(self, field)
            if not 0.0 <= value <= 1.0:
                raise ContractValidationError(f"{field} must be between 0 and 1")
        for field in ("latency_p50", "latency_p95", "context_growth", "quota_consumption"):
            _finite_non_negative(getattr(self, field), field)
        if self.user_acceptance is not None and not 0.0 <= self.user_acceptance <= 1.0:
            raise ContractValidationError("user_acceptance must be between 0 and 1")
        if self.latency_p95 < self.latency_p50:
            raise ContractValidationError("latency_p95 must be >= latency_p50")


PreferenceMode = Literal["auto", "ask", "learned"]


@dataclass(frozen=True)
class LearnedPreference:
    """User preference learned from explicit choices and subsequent outcomes."""

    scope: str
    task_signature: str
    preferred_route: str
    mode: PreferenceMode
    confidence: float
    evidence_count: int
    success_rate: float
    agreement_rate: float = 0.0
    reset_generation: int = 0

    def __post_init__(self) -> None:
        if not self.scope.strip() or not self.task_signature.strip():
            raise ContractValidationError("preference scope and task_signature must be non-empty")
        if not self.preferred_route.strip():
            raise ContractValidationError("preferred_route must be non-empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ContractValidationError("confidence must be between 0 and 1")
        if self.evidence_count < 0:
            raise ContractValidationError("evidence_count must be >= 0")
        if not 0.0 <= self.success_rate <= 1.0:
            raise ContractValidationError("success_rate must be between 0 and 1")
        if not 0.0 <= self.agreement_rate <= 1.0:
            raise ContractValidationError("agreement_rate must be between 0 and 1")
        if self.reset_generation < 0:
            raise ContractValidationError("reset_generation must be >= 0")
