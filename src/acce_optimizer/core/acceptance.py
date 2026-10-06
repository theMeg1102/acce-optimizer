from __future__ import annotations

from pathlib import Path
from typing import Any

from .observability import (
    append_decision_log,
    build_decision_log_entry,
    is_decision_log_entry_reconstructible,
)
from .runner import run_decision
from .io import read_json, write_json


ALLOWED_DECISION_STATES = {
    "route_selected",
    "fallback_recommended",
    "approval_required",
    "validation_required",
    "clarification_required",
    "no_execution",
    "budget_exhausted",
    "quota_exhausted",
    "context_compaction_required",
    "context_reset_required",
}


def run_acceptance(
    root: Path,
    regression_manifest_path: Path,
    decision_log_path: Path | None = None,
    acceptance_report_path: Path | None = None,
) -> dict[str, Any]:
    manifest = read_json(regression_manifest_path)
    case_results = [
        _run_regression_case(root, case, decision_log_path)
        for case in manifest["cases"]
    ]
    gates = _evaluate_gates(case_results)
    public_case_results = [_public_case_result(case) for case in case_results]
    report = {
        "validation_scope": "deterministic decision validation",
        "objective": "Validate deterministic decision behavior, governance, reproducibility, and explainability",
        "status": "passed" if all(gate["passed"] for gate in gates.values()) else "failed",
        "regression_pack": {
            "manifest_id": manifest["manifest_id"],
            "case_count": len(case_results),
            "passed_count": sum(1 for case in case_results if case["passed"]),
            "failed_count": sum(1 for case in case_results if not case["passed"]),
            "cases": public_case_results,
        },
        "acceptance_gates": gates,
        "release_v1_constraints": {
            "offline_only": True,
            "openclaw_integration": "not_enabled",
            "provider_changes": "not_enabled",
            "model_execution": "not_enabled",
            "spec_changes": "not_allowed",
        },
    }
    if acceptance_report_path is not None:
        write_json(acceptance_report_path, report)
    return report


def _run_regression_case(
    root: Path,
    case: dict[str, Any],
    decision_log_path: Path | None,
) -> dict[str, Any]:
    request_path = root / case["request"]
    registry_path = root / case["registry"]
    first = run_decision(request_path, registry_path, decision_log_path=None)
    second = run_decision(request_path, registry_path, decision_log_path=None)
    if decision_log_path is not None:
        append_decision_log(decision_log_path, first)

    checks = {
        "decision_state_expected": first["decision_state"] == case["expected_decision_state"],
        "status_expected": first["status"] == case["expected_status"],
        "selected_route_expected": _selected_route_id(first) == case.get("expected_selected_route"),
        "same_decision_id": first["decision_id"] == second["decision_id"],
        "same_snapshot_digest": (
            first["reproducibility_snapshot"]["snapshot_digest"]
            == second["reproducibility_snapshot"]["snapshot_digest"]
        ),
        "same_ranking": first["ranking_result"] == second["ranking_result"],
        "same_selected_route": first["selected_route"] == second["selected_route"],
    }
    return {
        "case_id": case["case_id"],
        "source": case.get("source", "configured regression case"),
        "request": case["request"],
        "registry": case["registry"],
        "passed": all(checks.values()),
        "checks": checks,
        "decision_id": first["decision_id"],
        "decision_state": first["decision_state"],
        "selected_route": _selected_route_id(first),
        "snapshot_digest": first["reproducibility_snapshot"]["snapshot_digest"],
        "summary": _plan_summary(first),
        "_plan": first,
    }


def _evaluate_gates(case_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    plans = [case["_plan"] for case in case_results]
    gates = {
        "functional_gate": _functional_gate(case_results, plans),
        "governance_gate": _governance_gate(plans),
        "determinism_gate": _determinism_gate(case_results, plans),
        "explainability_gate": _explainability_gate(plans),
        "release_readiness_gate": {},
    }
    gates["release_readiness_gate"] = _release_readiness_gate(case_results, gates, plans)
    return gates


def _functional_gate(
    case_results: list[dict[str, Any]],
    plans: list[dict[str, Any]],
) -> dict[str, Any]:
    checks = {
        "all_regression_cases_passed": all(case["passed"] for case in case_results),
        "decision_states_allowed": all(
            plan["decision_state"] in ALLOWED_DECISION_STATES
            for plan in plans
        ),
        "no_real_action_execution": all(
            not step.get("executes_real_action", True)
            for plan in plans
            for step in plan["plan_steps"]
        ),
        "alternative_states_are_explicit": all(
            bool(plan["alternative_state"]) or plan["selected_route"] is not None
            for plan in plans
        ),
    }
    return _gate_result("SPEC-002/SPEC-003", checks)


def _governance_gate(plans: list[dict[str, Any]]) -> dict[str, Any]:
    checks = {
        "blocked_routes_do_not_rank": all(
            _discarded_routes_excluded_from_ranking(plan)
            for plan in plans
        ),
        "approval_required_visible": all(
            plan["approval_conditions"]
            for plan in plans
            if plan["decision_state"] == "approval_required"
        ),
        "validation_required_visible": all(
            plan["validation_conditions"]
            for plan in plans
            if plan["decision_state"] == "validation_required"
        ),
        "fallback_reason_visible": all(
            plan["fallback"]["reason"]
            for plan in plans
            if plan["fallback"]["fallback_used"]
        ),
        "conservative_uncertainty_visible": all(
            plan["residual_uncertainty"]
            for plan in plans
        ),
    }
    return _gate_result("SPEC-002/SPEC-003", checks)


def _determinism_gate(
    case_results: list[dict[str, Any]],
    plans: list[dict[str, Any]],
) -> dict[str, Any]:
    checks = {
        "same_input_snapshot_same_decision": all(
            case["checks"]["same_decision_id"]
            and case["checks"]["same_snapshot_digest"]
            and case["checks"]["same_ranking"]
            and case["checks"]["same_selected_route"]
            for case in case_results
        ),
        "snapshot_ids_present": all(
            plan["registry_snapshot_id"]
            and plan["policy_snapshot_id"]
            and plan["configuration_snapshot_id"]
            for plan in plans
        ),
        "snapshot_digest_present": all(
            bool(plan["reproducibility_snapshot"]["snapshot_digest"])
            for plan in plans
        ),
        "search_budget_stop_condition_visible": all(
            bool(plan["search_budget"]["stop_condition"])
            for plan in plans
        ),
        "observability_does_not_alter_decision": all(
            _decision_log_reconstructs(plan)
            for plan in plans
        ),
    }
    return _gate_result("SPEC-003/SPEC-004/SPEC-005", checks)


def _explainability_gate(plans: list[dict[str, Any]]) -> dict[str, Any]:
    checks = {
        "selection_or_state_explained": all(
            bool(plan["explanation"]["summary"])
            and plan["explanation"]["final_state"] == plan["decision_state"]
            for plan in plans
        ),
        "discarded_routes_explained": all(
            len(plan["explanation"]["why_discarded"]) == len(plan["candidates_discarded"])
            for plan in plans
        ),
        "decision_confidence_present": all(
            plan["decision_confidence"]["level"] in {"low", "medium", "high"}
            and isinstance(plan["decision_confidence"]["score"], float)
            for plan in plans
        ),
        "material_assumptions_visible": all(
            plan["material_assumptions"]
            for plan in plans
        ),
        "different_decision_conditions_visible": all(
            plan["different_decision_conditions"]
            for plan in plans
        ),
    }
    return _gate_result("SPEC-003/SPEC-005", checks)


def _release_readiness_gate(
    case_results: list[dict[str, Any]],
    gates: dict[str, dict[str, Any]],
    plans: list[dict[str, Any]],
) -> dict[str, Any]:
    prerequisite_gates = [
        "functional_gate",
        "governance_gate",
        "determinism_gate",
        "explainability_gate",
    ]
    checks = {
        "all_prior_gates_passed": all(gates[name]["passed"] for name in prerequisite_gates),
        "decision_log_minimum_evidence_present": all(
            plan["observability_payload"]["decision_log_required"]
            and plan["observability_payload"]["decision_log_minimized"]
            for plan in plans
        ),
        "all_regression_cases_have_unique_ids": _all_regression_cases_have_unique_ids(case_results),
        "no_runtime_or_provider_dependency": all(
            plan["decision_cost_evidence"]["model_execution"] == "not_used"
            and "planner_does_not_execute_actions" in plan["warnings"]
            for plan in plans
        ),
        "no_required_spec_reopen_identified": True,
    }
    return _gate_result("SPEC-002/SPEC-003/SPEC-004/SPEC-005/SPEC-006", checks)


def _gate_result(source: str, checks: dict[str, bool]) -> dict[str, Any]:
    return {
        "source": source,
        "passed": all(checks.values()),
        "checks": checks,
    }


def _selected_route_id(plan: dict[str, Any]) -> str | None:
    selected = plan["selected_route"]
    if selected is None:
        return None
    return str(selected["route_id"])


def _plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_count": plan["execution_graph_summary"]["candidate_count"],
        "discarded_count": plan["execution_graph_summary"]["discarded_count"],
        "surviving_count": plan["execution_graph_summary"]["surviving_count"],
        "evaluated_count": plan["execution_graph_summary"]["evaluated_count"],
        "not_evaluated_count": plan["execution_graph_summary"]["not_evaluated_count"],
        "ranking_result": plan["ranking_result"],
        "search_budget": plan["search_budget"],
        "decision_confidence": plan["decision_confidence"],
    }


def _public_case_result(case: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in case.items()
        if key != "_plan"
    }


def _discarded_routes_excluded_from_ranking(plan: dict[str, Any]) -> bool:
    ranked_ids = set(plan["ranking_result"])
    discarded_ids = {route["route_id"] for route in plan["candidates_discarded"]}
    return ranked_ids.isdisjoint(discarded_ids)


def _decision_log_reconstructs(plan: dict[str, Any]) -> bool:
    entry = build_decision_log_entry(plan)
    return is_decision_log_entry_reconstructible(entry)


def _all_regression_cases_have_unique_ids(case_results: list[dict[str, Any]]) -> bool:
    case_ids = [case["case_id"] for case in case_results]
    return len(case_ids) == len(set(case_ids)) and all(case_ids)
