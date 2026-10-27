from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping

from .errors import ContractValidationError
from .runtime import QuotaPolicy


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} must be a non-empty string")
    return value


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractValidationError(f"{field} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True)
class OpenClawStatusObservation:
    runtime_version: str
    gateway_version: str
    selected_model: str
    runtime: str
    current_tokens: int
    context_window_tokens: int
    remaining_tokens: int
    percent_used: int
    quota_remaining_fraction: float
    quota_window_label: str
    quota_reset_at: datetime
    quota_reset_after_seconds: int
    quota_window_seconds: int
    session_updated_at: datetime
    usage_updated_at: datetime
    provider: str
    plan: str

    def as_safe_evidence(self) -> dict[str, Any]:
        return {
            "source": "openclaw_status_json_usage",
            "runtime_version": self.runtime_version,
            "gateway_version": self.gateway_version,
            "selected_model": self.selected_model,
            "runtime": self.runtime,
            "current_tokens": self.current_tokens,
            "context_window_tokens": self.context_window_tokens,
            "remaining_tokens": self.remaining_tokens,
            "percent_used": self.percent_used,
            "provider": self.provider,
            "plan": self.plan,
            "quota_remaining_fraction": self.quota_remaining_fraction,
            "quota_window_label": self.quota_window_label,
            "quota_reset_at": self.quota_reset_at.isoformat(),
            "quota_reset_after_seconds": self.quota_reset_after_seconds,
            "quota_window_seconds": self.quota_window_seconds,
            "session_updated_at": self.session_updated_at.isoformat(),
            "usage_updated_at": self.usage_updated_at.isoformat(),
            "billing_usd": None,
            "compaction_state": "unavailable_from_status",
            "session_identifier_preserved": False,
            "flags_preserved": False,
        }

    def quota_policy(self) -> QuotaPolicy:
        return QuotaPolicy(
            provider_id=self.provider,
            remaining_fraction=self.quota_remaining_fraction,
            reset_after_seconds=self.quota_reset_after_seconds,
            window_seconds=self.quota_window_seconds,
        )

    @classmethod
    def from_safe_evidence(cls, evidence: Mapping[str, Any]) -> "OpenClawStatusObservation":
        """Rehydrate only the minimized evidence emitted by ``as_safe_evidence``."""
        evidence = _object(evidence, "OpenClaw safe evidence")
        if evidence.get("source") != "openclaw_status_json_usage":
            raise ContractValidationError("OpenClaw safe evidence source is unsupported")
        if evidence.get("session_identifier_preserved") is not False:
            raise ContractValidationError("OpenClaw safe evidence must not preserve a session identifier")
        if evidence.get("flags_preserved") is not False:
            raise ContractValidationError("OpenClaw safe evidence must not preserve session flags")
        if evidence.get("billing_usd") is not None:
            raise ContractValidationError("subscription quota must not be represented as USD billing")

        def timestamp(field: str) -> datetime:
            value = _text(evidence.get(field), field)
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ContractValidationError(f"{field} must be an RFC 3339 timestamp") from error
            if parsed.tzinfo is None:
                raise ContractValidationError(f"{field} must include a timezone")
            return parsed

        remaining_fraction = evidence.get("quota_remaining_fraction")
        if (
            isinstance(remaining_fraction, bool)
            or not isinstance(remaining_fraction, (int, float))
            or not 0 <= float(remaining_fraction) <= 1
        ):
            raise ContractValidationError("quota_remaining_fraction must be between 0 and 1")
        current = _integer(evidence.get("current_tokens"), "current_tokens")
        window = _integer(evidence.get("context_window_tokens"), "context_window_tokens", 1)
        remaining = _integer(evidence.get("remaining_tokens"), "remaining_tokens")
        percent = _integer(evidence.get("percent_used"), "percent_used")
        if current > window or remaining > window or percent > 100:
            raise ContractValidationError("safe session token telemetry is inconsistent")
        reset_after = _integer(
            evidence.get("quota_reset_after_seconds"),
            "quota_reset_after_seconds",
        )
        window_seconds = _integer(
            evidence.get("quota_window_seconds"),
            "quota_window_seconds",
            1,
        )
        if reset_after > window_seconds:
            raise ContractValidationError("quota reset exceeds the observed window")
        return cls(
            runtime_version=_text(evidence.get("runtime_version"), "runtime_version"),
            gateway_version=_text(evidence.get("gateway_version"), "gateway_version"),
            selected_model=_text(evidence.get("selected_model"), "selected_model"),
            runtime=_text(evidence.get("runtime"), "runtime"),
            current_tokens=current,
            context_window_tokens=window,
            remaining_tokens=remaining,
            percent_used=percent,
            quota_remaining_fraction=float(remaining_fraction),
            quota_window_label=_text(evidence.get("quota_window_label"), "quota_window_label"),
            quota_reset_at=timestamp("quota_reset_at"),
            quota_reset_after_seconds=reset_after,
            quota_window_seconds=window_seconds,
            session_updated_at=timestamp("session_updated_at"),
            usage_updated_at=timestamp("usage_updated_at"),
            provider=_text(evidence.get("provider"), "provider"),
            plan=_text(evidence.get("plan"), "plan"),
        )


class OpenClawStatusAdapter:
    """Read-only parser for the supported `openclaw status --json --usage` surface."""

    @staticmethod
    def _epoch_ms(value: Any, field: str) -> datetime:
        milliseconds = _integer(value, field)
        try:
            return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise ContractValidationError(f"{field} is outside the supported epoch range") from error

    @staticmethod
    def _window_seconds(value: Any) -> int:
        label = _text(value, "usage window label")
        match = re.fullmatch(r"([1-9][0-9]*)([mhd])", label)
        if match is None:
            raise ContractValidationError("usage window label has an unsupported duration")
        units = {"m": 60, "h": 3_600, "d": 86_400}
        return int(match.group(1)) * units[match.group(2)]

    @classmethod
    def observe(
        cls,
        payload: Mapping[str, Any],
        *,
        session_key: str,
        now: datetime | None = None,
        max_usage_age_seconds: int = 900,
    ) -> OpenClawStatusObservation:
        payload = _object(payload, "OpenClaw status")
        reference = now or datetime.now(timezone.utc)
        gateway = _object(payload.get("gateway"), "gateway")
        if gateway.get("reachable") is not True:
            raise ContractValidationError("OpenClaw gateway is not reachable")
        gateway_self = _object(gateway.get("self"), "gateway.self")
        runtime_version = _text(payload.get("runtimeVersion"), "runtimeVersion")
        gateway_version = _text(gateway_self.get("version"), "gateway.self.version")
        if runtime_version != gateway_version:
            raise ContractValidationError("OpenClaw runtime and gateway versions differ")

        sessions = _object(payload.get("sessions"), "sessions").get("recent")
        if not isinstance(sessions, list):
            raise ContractValidationError("sessions.recent must be a list")
        matches = [item for item in sessions if isinstance(item, Mapping) and item.get("key") == session_key]
        if len(matches) != 1:
            raise ContractValidationError("exactly one requested session must be present")
        session = matches[0]
        if session.get("totalTokensFresh") is not True:
            raise ContractValidationError("session token telemetry is not fresh")
        if session.get("abortedLastRun") is not False:
            raise ContractValidationError("last OpenClaw run was aborted")
        current = _integer(session.get("totalTokens"), "totalTokens")
        window = _integer(session.get("contextTokens"), "contextTokens", 1)
        remaining = _integer(session.get("remainingTokens"), "remainingTokens")
        percent = _integer(session.get("percentUsed"), "percentUsed")
        if percent > 100 or current > window or remaining > window:
            raise ContractValidationError("session token telemetry is inconsistent")
        session_updated = cls._epoch_ms(session.get("updatedAt"), "session.updatedAt")

        usage = _object(payload.get("usage"), "usage")
        usage_updated = cls._epoch_ms(usage.get("updatedAt"), "usage.updatedAt")
        age = (reference.astimezone(timezone.utc) - usage_updated).total_seconds()
        if age < -60 or age > max_usage_age_seconds:
            raise ContractValidationError("OpenClaw usage telemetry is stale or from the future")
        selected_model = _text(session.get("selectedModel"), "selectedModel")
        provider_id = selected_model.split("/", 1)[0]
        providers = usage.get("providers")
        if not isinstance(providers, list):
            raise ContractValidationError("usage.providers must be a list")
        provider_matches = [item for item in providers if isinstance(item, Mapping) and item.get("provider") == provider_id]
        if len(provider_matches) != 1:
            raise ContractValidationError("exactly one matching usage provider is required")
        provider = provider_matches[0]
        windows = provider.get("windows")
        if not isinstance(windows, list) or not windows:
            raise ContractValidationError("provider usage window is required")
        window_data = _object(windows[0], "usage window")
        used_percent = _integer(window_data.get("usedPercent"), "usedPercent")
        if used_percent > 100:
            raise ContractValidationError("usedPercent must be <= 100")
        quota_window_label = _text(window_data.get("label"), "usage window label")
        quota_window_seconds = cls._window_seconds(quota_window_label)
        quota_reset_at = cls._epoch_ms(window_data.get("resetAt"), "usage resetAt")
        quota_reset_after_seconds = int(
            (quota_reset_at - reference.astimezone(timezone.utc)).total_seconds()
        )
        if quota_reset_after_seconds < 0 or quota_reset_after_seconds > quota_window_seconds:
            raise ContractValidationError("usage resetAt is inconsistent with the observed window")

        return OpenClawStatusObservation(
            runtime_version=runtime_version,
            gateway_version=gateway_version,
            selected_model=selected_model,
            runtime=_text(session.get("runtime"), "runtime"),
            current_tokens=current,
            context_window_tokens=window,
            remaining_tokens=remaining,
            percent_used=percent,
            quota_remaining_fraction=round(1.0 - used_percent / 100.0, 6),
            quota_window_label=quota_window_label,
            quota_reset_at=quota_reset_at,
            quota_reset_after_seconds=quota_reset_after_seconds,
            quota_window_seconds=quota_window_seconds,
            session_updated_at=session_updated,
            usage_updated_at=usage_updated,
            provider=provider_id,
            plan=_text(provider.get("plan"), "provider plan"),
        )
