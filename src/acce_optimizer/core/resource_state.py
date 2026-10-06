from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .errors import ContractValidationError


def _finite_non_negative(value: float, field: str) -> float:
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        raise ContractValidationError(f"{field} must be a finite non-negative number")
    return float(value)


@dataclass(frozen=True)
class RefreshPolicy:
    """Installation-defined refresh policy for external resource state."""

    interval_minutes: int = 60

    def __post_init__(self) -> None:
        if self.interval_minutes < 1:
            raise ContractValidationError("interval_minutes must be >= 1")


@dataclass(frozen=True)
class ResourceState:
    """Immutable resource availability captured for one routing decision."""

    observed_at: datetime
    quota_remaining: float | None = None
    quota_limit: float | None = None
    budget_remaining: float | None = None
    budget_limit: float | None = None
    local_capacity: float | None = None
    quota_reset_at: datetime | None = None
    budget_reset_at: datetime | None = None
    quota_refresh_policy: RefreshPolicy = RefreshPolicy()
    budget_refresh_policy: RefreshPolicy = RefreshPolicy()

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ContractValidationError("observed_at must be timezone-aware")
        for field in (
            "quota_remaining",
            "quota_limit",
            "budget_remaining",
            "budget_limit",
            "local_capacity",
        ):
            value = getattr(self, field)
            if value is not None:
                _finite_non_negative(value, field)

        for remaining, limit, prefix in (
            (self.quota_remaining, self.quota_limit, "quota"),
            (self.budget_remaining, self.budget_limit, "budget"),
        ):
            if remaining is not None and limit is not None and remaining > limit:
                raise ContractValidationError(
                    f"{prefix}_remaining must not exceed {prefix}_limit"
                )

        if self.quota_reset_at is not None and self.quota_reset_at.tzinfo is None:
            raise ContractValidationError("quota_reset_at must be timezone-aware")
        if self.budget_reset_at is not None and self.budget_reset_at.tzinfo is None:
            raise ContractValidationError("budget_reset_at must be timezone-aware")

    def quota_fraction_remaining(self) -> float | None:
        if self.quota_remaining is None or self.quota_limit in (None, 0):
            return None
        return self.quota_remaining / self.quota_limit

    def budget_fraction_remaining(self) -> float | None:
        if self.budget_remaining is None or self.budget_limit in (None, 0):
            return None
        return self.budget_remaining / self.budget_limit

    def needs_quota_refresh(self, now: datetime) -> bool:
        return self._needs_refresh(now, self.quota_reset_at, self.quota_refresh_policy)

    def needs_budget_refresh(self, now: datetime) -> bool:
        return self._needs_refresh(now, self.budget_reset_at, self.budget_refresh_policy)

    def _needs_refresh(
        self,
        now: datetime,
        reset_at: datetime | None,
        policy: RefreshPolicy,
    ) -> bool:
        if now.tzinfo is None:
            raise ContractValidationError("now must be timezone-aware")
        return now >= self.observed_at + timedelta(minutes=policy.interval_minutes)
