from __future__ import annotations

import json
import hashlib
import fcntl
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("America/Mexico_City")


def build_decision_log_entry(plan: dict[str, Any]) -> dict[str, Any]:
    normalized_request = _minimized_request(plan["normalized_request"])
    reproducibility_snapshot = deepcopy(plan["reproducibility_snapshot"])
    if "request" in reproducibility_snapshot:
        reproducibility_snapshot["request"] = _minimized_request(
            reproducibility_snapshot["request"]
        )
    reproducibility_snapshot["logged_snapshot_digest"] = _snapshot_digest(
        reproducibility_snapshot,
        excluded={"logged_snapshot_digest"},
    )
    return {
        "logged_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "logged_at_local": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        "decision_id": plan["decision_id"],
        "decision_state": plan["decision_state"],
        "normalized_request": normalized_request,
        "profile_used": plan["profile_used"],
        "policy_snapshot_id": plan["policy_snapshot_id"],
        "configuration_snapshot_id": plan["configuration_snapshot_id"],
        "registry_snapshot_id": plan["registry_snapshot_id"],
        "reproducibility_snapshot": reproducibility_snapshot,
        "candidates_generated": plan["candidates_generated"],
        "candidates_discarded": plan["candidates_discarded"],
        "candidates_surviving": plan["candidates_surviving"],
        "routes_evaluated": plan["routes_evaluated"],
        "routes_not_evaluated": plan["routes_not_evaluated"],
        "ranking_result": plan["ranking_result"],
        "selected_route": plan["selected_route"],
        "search_budget": plan["search_budget"],
        "decision_confidence": plan["decision_confidence"],
        "cost_estimates": {
            "decision": plan["decision_cost_evidence"],
            "execution": plan["execution_cost_evidence"],
        },
        "economic_guardrail": plan["economic_guardrail"],
        "quota_guardrail": plan["quota_guardrail"],
        "context_guardrail": plan["context_guardrail"],
        "validation_conditions": plan["validation_conditions"],
        "fallback": plan["fallback"],
        "explanation": plan["explanation"],
        "residual_uncertainty": plan["residual_uncertainty"],
        "material_assumptions": plan["material_assumptions"],
    }


def append_decision_log(path: Path, plan: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = build_decision_log_entry(plan)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o640)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _minimized_request(request: dict[str, Any]) -> dict[str, Any]:
    minimized = deepcopy(request)
    summary = minimized.pop("summary", None)
    if isinstance(summary, str):
        minimized["summary_sha256"] = hashlib.sha256(summary.encode("utf-8")).hexdigest()
        minimized["summary_length"] = len(summary)
    return minimized


def _snapshot_digest(snapshot: dict[str, Any], excluded: set[str]) -> str:
    source = {key: value for key, value in snapshot.items() if key not in excluded}
    return hashlib.sha256(json.dumps(source, sort_keys=True).encode("utf-8")).hexdigest()


def reconstruct_decision_id_from_log_entry(entry: dict[str, Any]) -> str:
    selected = entry["selected_route"]
    source = {
        "reproducibility_snapshot_digest": entry["reproducibility_snapshot"]["snapshot_digest"],
        "selected_route": selected["route_id"] if selected else None,
        "decision_state": entry["decision_state"],
    }
    digest = hashlib.sha256(json.dumps(source, sort_keys=True).encode("utf-8")).hexdigest()
    return f"acce-decision-{digest[:16]}"


def is_decision_log_entry_reconstructible(entry: dict[str, Any]) -> bool:
    required_fields = {
        "decision_id",
        "decision_state",
        "normalized_request",
        "policy_snapshot_id",
        "configuration_snapshot_id",
        "registry_snapshot_id",
        "reproducibility_snapshot",
        "candidates_generated",
        "candidates_discarded",
        "routes_evaluated",
        "ranking_result",
        "selected_route",
        "search_budget",
        "decision_confidence",
        "explanation",
    }
    if not required_fields.issubset(entry):
        return False
    if "snapshot_digest" not in entry["reproducibility_snapshot"]:
        return False
    snapshot = entry["reproducibility_snapshot"]
    if "logged_snapshot_digest" in snapshot:
        if _snapshot_digest(snapshot, {"logged_snapshot_digest"}) != snapshot["logged_snapshot_digest"]:
            return False
    return reconstruct_decision_id_from_log_entry(entry) == entry["decision_id"]
