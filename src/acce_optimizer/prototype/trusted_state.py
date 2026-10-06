from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import math
from pathlib import Path
from typing import Any, Mapping

from .errors import ContractValidationError
from .io import read_json, write_json
from .runtime import ContextPolicy, EconomicPolicy, QuotaPolicy


def _finite(value: Any, field: str, *, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (maximum is not None and result > maximum):
        raise ContractValidationError(f"{field} is outside its allowed range")
    return result


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ContextTelemetry:
    session_key: str
    active_model: str
    current_tokens: int
    context_window_tokens: int
    cloud_quota_remaining_fraction: float
    compaction_count: int
    compaction_in_progress: bool
    observed_at: datetime

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        now: datetime | None = None,
        max_age_seconds: int = 300,
    ) -> "ContextTelemetry":
        if not isinstance(data, Mapping):
            raise ContractValidationError("context telemetry must be an object")
        observed_raw = _text(data.get("observed_at"), "observed_at")
        try:
            observed = datetime.fromisoformat(observed_raw.replace("Z", "+00:00"))
        except ValueError as error:
            raise ContractValidationError("observed_at must be ISO-8601") from error
        if observed.tzinfo is None:
            raise ContractValidationError("observed_at must include a timezone")
        reference = now or datetime.now(timezone.utc)
        age = (reference.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
        if age < -60 or age > max_age_seconds:
            raise ContractValidationError("context telemetry is stale or from the future")
        current = data.get("current_tokens")
        window = data.get("context_window_tokens")
        count = data.get("compaction_count", 0)
        for value, field, minimum in (
            (current, "current_tokens", 0),
            (window, "context_window_tokens", 1),
            (count, "compaction_count", 0),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ContractValidationError(f"{field} must be an integer >= {minimum}")
        if current > window:
            raise ContractValidationError("current_tokens cannot exceed context_window_tokens")
        in_progress = data.get("compaction_in_progress", False)
        if not isinstance(in_progress, bool):
            raise ContractValidationError("compaction_in_progress must be a boolean")
        return cls(
            session_key=_text(data.get("session_key"), "session_key"),
            active_model=_text(data.get("active_model"), "active_model"),
            current_tokens=current,
            context_window_tokens=window,
            cloud_quota_remaining_fraction=_finite(
                data.get("cloud_quota_remaining_fraction", 1.0),
                "cloud_quota_remaining_fraction",
                maximum=1.0,
            ),
            compaction_count=count,
            compaction_in_progress=in_progress,
            observed_at=observed,
        )

    def context_policy(self) -> ContextPolicy:
        return ContextPolicy(
            compact_at_tokens=max(1, int(self.context_window_tokens * 0.75)),
            reset_at_tokens=max(1, int(self.context_window_tokens * 0.95)),
            hard_limit_tokens=self.context_window_tokens,
            compaction_enabled=not self.compaction_in_progress,
        )


class MonthlyUsageLedger:
    """Atomic, idempotent local ledger; contains accounting data, never secrets."""

    schema = "acce_optimizer.monthly-cloud-usage.v1"

    def __init__(self, path: Path, *, period: str, budget_usd: float = 20.0) -> None:
        self.path = path
        self.period = _text(period, "period")
        self.budget_usd = _finite(budget_usd, "budget_usd")

    def _empty(self) -> dict[str, Any]:
        return {"schema": self.schema, "period": self.period, "budget_usd": self.budget_usd, "entries": []}

    def _load(self) -> dict[str, Any]:
        data = read_json(self.path) if self.path.exists() else self._empty()
        if data.get("schema") != self.schema or data.get("period") != self.period:
            raise ContractValidationError("usage ledger schema or period mismatch")
        if _finite(data.get("budget_usd"), "budget_usd") != self.budget_usd:
            raise ContractValidationError("usage ledger budget differs from trusted configuration")
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise ContractValidationError("usage ledger entries must be a list")
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ContractValidationError("usage ledger entry must be an object")
            event_id = _text(entry.get("event_id"), "event_id")
            if event_id in seen:
                raise ContractValidationError("usage ledger contains duplicate event_id")
            seen.add(event_id)
            _finite(entry.get("amount_usd"), "amount_usd")
            _text(entry.get("provider_id"), "provider_id")
            _text(entry.get("recorded_at"), "recorded_at")
        return data

    def record(self, *, event_id: str, amount_usd: float, provider_id: str, recorded_at: str) -> bool:
        event_id = _text(event_id, "event_id")
        amount = _finite(amount_usd, "amount_usd")
        provider_id = _text(provider_id, "provider_id")
        recorded_at = _text(recorded_at, "recorded_at")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            data = self._load()
            if any(entry["event_id"] == event_id for entry in data["entries"]):
                return False
            data["entries"].append({
                "event_id": event_id,
                "amount_usd": amount,
                "provider_id": provider_id,
                "recorded_at": recorded_at,
            })
            write_json(self.path, data)
            return True

    def economic_policy(self, *, quota_remaining_fraction: float = 1.0) -> EconomicPolicy:
        data = self._load()
        spend = round(sum(float(entry["amount_usd"]) for entry in data["entries"]), 6)
        return EconomicPolicy(
            monthly_cloud_budget_usd=self.budget_usd,
            monthly_cloud_spend_usd=spend,
            cloud_quota_remaining_fraction=_finite(
                quota_remaining_fraction, "quota_remaining_fraction", maximum=1.0
            ),
            budget_period=self.period,
        )


@dataclass(frozen=True)
class TrustedRuntimeState:
    economic_policy: EconomicPolicy
    quota_policy: QuotaPolicy
    context_policy: ContextPolicy
    context_current_tokens: int
    session_key: str
    active_model: str
    compaction_count: int
    compaction_in_progress: bool

    @classmethod
    def from_files(
        cls,
        *,
        ledger: MonthlyUsageLedger,
        telemetry_path: Path,
        now: datetime | None = None,
        max_telemetry_age_seconds: int = 300,
    ) -> "TrustedRuntimeState":
        telemetry = ContextTelemetry.from_mapping(
            read_json(telemetry_path), now=now, max_age_seconds=max_telemetry_age_seconds
        )
        return cls(
            economic_policy=ledger.economic_policy(
                quota_remaining_fraction=telemetry.cloud_quota_remaining_fraction
            ),
            quota_policy=QuotaPolicy(
                remaining_fraction=telemetry.cloud_quota_remaining_fraction
            ),
            context_policy=telemetry.context_policy(),
            context_current_tokens=telemetry.current_tokens,
            session_key=telemetry.session_key,
            active_model=telemetry.active_model,
            compaction_count=telemetry.compaction_count,
            compaction_in_progress=telemetry.compaction_in_progress,
        )
