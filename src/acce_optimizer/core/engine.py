from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import CandidateRoute, DecisionRequest
from .registry import CapabilityRegistry


PROFILE_WEIGHTS = {
    "safety_first": {
        "cloud_cost": 0.0,
        "latency": 0.5,
        "quality_deficit": 1.0,
        "privacy": 5.0,
        "risk": 5.0,
        "availability": 2.0,
        "complexity": 2.0,
        "cloud_quota": 2.0,
    },
    "balanced": {
        "cloud_cost": 0.0,
        "latency": 1.0,
        "quality_deficit": 2.0,
        "privacy": 2.0,
        "risk": 2.0,
        "availability": 1.0,
        "complexity": 1.0,
        "cloud_quota": 2.0,
    },
    "balanced_local_first": {
        "cloud_cost": 0.0,
        "latency": 1.0,
        "quality_deficit": 1.5,
        "privacy": 2.0,
        "risk": 2.0,
        "availability": 1.0,
        "complexity": 1.0,
        "cloud_quota": 3.0,
    },
    "cost_first": {
        "cloud_cost": 0.0,
        "latency": 0.5,
        "quality_deficit": 1.0,
        "privacy": 2.0,
        "risk": 2.0,
        "availability": 1.0,
        "complexity": 3.0,
        "cloud_quota": 3.0,
    },
}


def build_execution_plan(request: DecisionRequest, registry: CapabilityRegistry) -> dict[str, Any]:
    effective_profile = request.profile if request.profile in PROFILE_WEIGHTS else "balanced"
    candidate_routes = _candidate_routes(request, registry)
    discarded_routes: list[dict[str, Any]] = []
    surviving_routes: list[CandidateRoute] = []
    routes_evaluated: list[dict[str, Any]] = []
    routes_not_evaluated: list[dict[str, Any]] = []
    stop_condition = "not_started"
    early_exit_applied = False

    if request.clarification_required:
        selected = None
        ranked_routes: list[dict[str, Any]] = []
        decision_state = "clarification_required"
        stop_condition = "required_decision_information_missing"
    else:
        for route in candidate_routes:
            blocker = route_blocking_reason(request, route)
            if blocker:
                discarded_routes.append(_discarded_route(route, blocker))
            else:
                surviving_routes.append(route)

        max_routes = max(request.search_budget_max_candidate_routes, 0)
        for route_index, route in enumerate(surviving_routes):
            if len(routes_evaluated) >= max_routes:
                routes_not_evaluated.append(
                    {
                        "route_id": route.route_id,
                        "not_evaluated_reason": "search_budget_exhausted",
                    }
                )
                continue

            evaluated = _evaluate_route(request, route, effective_profile)
            routes_evaluated.append(evaluated)

            pending_routes = surviving_routes[route_index + 1 :]
            if _should_early_exit(
                request,
                evaluated,
                pending_routes,
                effective_profile,
            ):
                early_exit_applied = True
                routes_not_evaluated.extend(
                    {
                        "route_id": pending.route_id,
                        "not_evaluated_reason": "early_exit_after_governed_admissible_route",
                    }
                    for pending in pending_routes
                )
                break

        ranked_routes = sorted(routes_evaluated, key=_ranking_key)
        selected = ranked_routes[0] if ranked_routes else None
        decision_state = _decision_state(request, selected, discarded_routes)
        stop_condition = _stop_condition(
            selected,
            decision_state,
            early_exit_applied,
            routes_not_evaluated,
        )

    fallback = _fallback(selected, discarded_routes)
    decision_confidence = _decision_confidence(
        request=request,
        candidate_routes=candidate_routes,
        discarded_routes=discarded_routes,
        surviving_routes=surviving_routes,
        routes_evaluated=routes_evaluated,
        routes_not_evaluated=routes_not_evaluated,
        selected=selected,
        fallback=fallback,
    )
    reproducibility_snapshot = _reproducibility_snapshot(
        request,
        registry,
        candidate_routes,
        effective_profile,
    )
    decision_id = _decision_id(reproducibility_snapshot, selected, decision_state)

    return {
        "decision_id": decision_id,
        "decision_engine": "authoritative",
        "status": "execution_plan_ready" if selected else "alternative_state_required",
        "decision_state": decision_state,
        "normalized_request": request.normalized(),
        "profile_used": effective_profile,
        "requested_profile": request.profile,
        "intent_graph_summary": {
            "task_class": request.task_class,
            "required_capabilities": list(request.required_capabilities),
        },
        "execution_graph_summary": {
            "candidate_count": len(candidate_routes),
            "discarded_count": len(discarded_routes),
            "surviving_count": len(surviving_routes),
            "evaluated_count": len(routes_evaluated),
            "not_evaluated_count": len(routes_not_evaluated),
        },
        "registry_snapshot_id": registry.snapshot_id,
        "policy_snapshot_id": registry.policy_snapshot_id,
        "configuration_snapshot_id": registry.configuration_snapshot_id,
        "reproducibility_snapshot": reproducibility_snapshot,
        "candidates_generated": [route.as_evidence() for route in candidate_routes],
        "candidates_discarded": discarded_routes,
        "discard_reasons": discarded_routes,
        "candidates_surviving": [route.as_evidence() for route in surviving_routes],
        "routes_evaluated": routes_evaluated,
        "routes_not_evaluated": routes_not_evaluated,
        "ranking_result": [route["route_id"] for route in ranked_routes],
        "selected_route": selected,
        "selection_criteria": "minimum_quota_first_graph_cost_after_hard_constraints_within_search_budget",
        "tie_breaker_applied": "stable_route_id_order" if _has_tie(ranked_routes) else "not_required",
        "search_budget": {
            "max_candidate_routes": request.search_budget_max_candidate_routes,
            "routes_evaluated": len(routes_evaluated),
            "routes_not_evaluated": len(routes_not_evaluated),
            "early_exit_enabled": request.early_exit_enabled,
            "early_exit_applied": early_exit_applied,
            "early_exit_global_cost_threshold": request.early_exit_global_cost_threshold,
            "decision_cost_estimate": len(candidate_routes) + len(routes_evaluated),
            "stop_condition": stop_condition,
        },
        "decision_confidence": decision_confidence,
        "decision_cost_evidence": {
            "hypotheses_generated": len(candidate_routes),
            "routes_evaluated": len(routes_evaluated),
            "deterministic_only": True,
            "model_execution": "not_used",
        },
        "execution_cost_evidence": _execution_cost(selected),
        "quota_guardrail": _quota_guardrail(request, selected),
        "economic_guardrail": _economic_guardrail(request, selected),
        "context_guardrail": _context_guardrail(request),
        "plan_steps": _plan_steps(selected),
        "approval_conditions": _approval_conditions(decision_state, discarded_routes),
        "validation_conditions": _validation_conditions(request, decision_state, selected),
        "warnings": ["planner_does_not_execute_actions"],
        "fallback": fallback,
        "alternative_state": None if selected else decision_state,
        "residual_uncertainty": _residual_uncertainty(routes_not_evaluated),
        "explanation": _explanation(
            selected,
            discarded_routes,
            decision_state,
            fallback,
            stop_condition,
        ),
        "material_assumptions": [
            "Registry snapshot is the complete declared inventory for this decision",
            "Policy snapshot represents the active local-first operational policy",
            "Configuration snapshot captures the active Search Budget and profile weights",
        ],
        "different_decision_conditions": _different_decision_conditions(discarded_routes),
        "observability_payload": {
            "decision_log_required": True,
            "decision_log_minimized": True,
            "outcome_log_required": False,
        },
    }


def _candidate_routes(
    request: DecisionRequest, registry: CapabilityRegistry
) -> list[CandidateRoute]:
    candidates = []
    for capability_id in request.required_capabilities:
        candidates.extend(registry.candidates_for(capability_id))
    return candidates


def route_blocking_reason(request: DecisionRequest, route: CandidateRoute) -> str | None:
    if not route.metadata_complete:
        return "metadata_incomplete"
    if route.availability != "available":
        return "capability_instance_unavailable"
    if request.task_class not in route.supported_task_classes:
        return "unsupported_task_class"
    projected_context = _projected_context_tokens(request)
    if route.context_window_tokens is not None and projected_context > route.context_window_tokens:
        return "route_context_limit_exceeded"
    context_action = _context_action(request)
    if context_action == "compaction_in_progress" and route.quota_metered:
        return "context_compaction_in_progress"
    if context_action == "reset_required":
        return "context_reset_required"
    if context_action == "compaction_required" and route.quota_metered:
        return "context_compaction_required"
    if route.requires_network and (
        not request.external_network_allowed or not route.external_network_allowed
    ):
        return "external_network_not_allowed"
    if route.requires_tool_access and not _tool_allowed(request, route):
        return "tool_not_allowed"
    if route.privacy_level == "restricted_external" and request.privacy_level in {
        "confidential",
        "restricted",
        "unknown",
    }:
        return "privacy_level_not_allowed"
    if (request.approval_required or route.approval_required or route.requires_approval) and (
        not request.approval_granted
    ):
        return "approval_required_not_granted"
    if route.quota_metered and not _quota_observation_applies(request, route):
        return "cloud_quota_observation_unavailable"
    if route.monetary_metered and route.estimated_cloud_cost_usd > request.max_cloud_cost_usd:
        return "cloud_cost_limit_exceeded"
    if route.quota_metered and request.cloud_quota_remaining_fraction <= 0:
        return "cloud_quota_exhausted"
    if route.monetary_metered and route.estimated_cloud_cost_usd > _remaining_monthly_budget(request):
        return "monthly_cloud_budget_exhausted"
    if route.estimated_latency_ms > request.max_latency_ms:
        return "latency_limit_exceeded"
    if route.quality_score < request.min_quality_score:
        return "quality_floor_not_met"
    return None


def _discarded_route(route: CandidateRoute, blocker: str) -> dict[str, Any]:
    return {
        "route_id": route.route_id,
        "blocked_by": blocker,
        "block_type": "hard_constraint",
        "discard_stage": "Constraint Filter",
        "reconsider_if": _reconsider_condition(blocker),
    }


def _reconsider_condition(blocker: str) -> str:
    conditions = {
        "metadata_incomplete": "capability metadata completed in the active registry snapshot",
        "external_network_not_allowed": "external network explicitly allowed by active policy",
        "tool_not_allowed": "required tool explicitly allowed by active policy",
        "privacy_level_not_allowed": "privacy policy permits the candidate route for this request",
        "approval_required_not_granted": "required approval granted before decision",
        "cloud_cost_limit_exceeded": "budget limit increased by active policy",
        "latency_limit_exceeded": "latency limit increased by active policy",
        "quality_floor_not_met": "quality floor changed by active policy",
        "route_context_limit_exceeded": "a route with sufficient context capacity becomes available",
        "context_compaction_required": "context is compacted and the request is evaluated again",
        "context_compaction_in_progress": "the active OpenClaw compaction finishes and telemetry is refreshed",
        "context_reset_required": "session context is reset and the request is evaluated again",
        "cloud_quota_exhausted": "the provider quota window resets or a local route becomes admissible",
        "cloud_quota_observation_unavailable": "fresh OpenClaw quota telemetry becomes available for the route provider",
        "monthly_cloud_budget_exhausted": "a new budget period begins or the trusted ceiling changes",
    }
    return conditions.get(blocker, "registry metadata or policy changes in a future snapshot")


def _evaluate_route(
    request: DecisionRequest, route: CandidateRoute, effective_profile: str
) -> dict[str, Any]:
    weights = PROFILE_WEIGHTS[effective_profile]
    quality_deficit = round(1.0 - route.quality_score, 4)
    latency_normalized = round(route.estimated_latency_ms / max(request.max_latency_ms, 1), 4)
    quota_cost = _quota_cost(request, route)
    cloud_quota_penalty = quota_cost["penalty"]
    global_cost = round(
        latency_normalized * weights["latency"]
        + quality_deficit * weights["quality_deficit"]
        + route.privacy_penalty * weights["privacy"]
        + route.risk_score * weights["risk"]
        + route.availability_penalty * weights["availability"]
        + route.complexity_score * weights["complexity"]
        + cloud_quota_penalty * weights["cloud_quota"],
        4,
    )
    evidence = route.as_evidence()
    evidence.update(
        {
            "profile": effective_profile,
            "quality_deficit": quality_deficit,
            "global_cost": global_cost,
            "soft_penalties": {
                "latency_normalized": latency_normalized,
                "privacy_penalty": route.privacy_penalty,
                "risk_score": route.risk_score,
                "availability_penalty": route.availability_penalty,
                "complexity_score": route.complexity_score,
                "cloud_quota_penalty": cloud_quota_penalty,
            },
            "quota_cost_evidence": quota_cost,
        }
    )
    return evidence


def _ranking_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item["global_cost"],
        item["risk_score"],
        item["privacy_penalty"],
        item["quality_deficit"],
        item["estimated_cloud_cost_usd"] if item["monetary_metered"] else 0.0,
        item["estimated_latency_ms"],
        item["complexity_score"],
        item["requires_network"],
        item["route_id"],
    )


def _should_early_exit(
    request: DecisionRequest,
    evaluated: dict[str, Any],
    pending_routes: list[CandidateRoute],
    effective_profile: str,
) -> bool:
    if not request.early_exit_enabled:
        return False
    if not evaluated["early_exit_eligible"]:
        return False
    if evaluated["global_cost"] > request.early_exit_global_cost_threshold:
        return False

    # Early Exit is safe only when the selected route cannot be displaced by
    # any remaining admissible route under the exact deterministic ranking.
    current_key = _ranking_key(evaluated)
    return all(
        _ranking_key(_evaluate_route(request, pending, effective_profile)) >= current_key
        for pending in pending_routes
    )


def _tool_allowed(request: DecisionRequest, route: CandidateRoute) -> bool:
    if request.tools_allowed is True:
        return True
    if request.tools_allowed is False:
        return False
    if route.tool_id is None:
        return False
    return route.tool_id in request.tools_allowed


def _decision_state(
    request: DecisionRequest,
    selected: dict[str, Any] | None,
    discarded_routes: list[dict[str, Any]],
) -> str:
    if selected and selected.get("requires_validation"):
        return "validation_required"
    if selected and _fallback(selected, discarded_routes)["fallback_used"]:
        return "fallback_recommended"
    if selected:
        return "route_selected"
    blockers = {route["blocked_by"] for route in discarded_routes}
    if "context_reset_required" in blockers:
        return "context_reset_required"
    if "context_compaction_required" in blockers:
        return "context_compaction_required"
    if "context_compaction_in_progress" in blockers:
        return "context_compaction_in_progress"
    if "monthly_cloud_budget_exhausted" in blockers:
        return "budget_exhausted"
    if "cloud_quota_exhausted" in blockers:
        return "quota_exhausted"
    if "approval_required_not_granted" in blockers:
        return "approval_required"
    if "quality_floor_not_met" in blockers:
        return "validation_required"
    if not request.required_capabilities:
        return "clarification_required"
    return "no_execution"


def _stop_condition(
    selected: dict[str, Any] | None,
    decision_state: str,
    early_exit_applied: bool,
    routes_not_evaluated: list[dict[str, Any]],
) -> str:
    if early_exit_applied:
        return "early_exit_governed_route_cannot_be_reasonably_displaced"
    if routes_not_evaluated:
        return "search_budget_exhausted"
    if selected:
        return "evaluated_all_surviving_routes_within_search_budget"
    return {
        "approval_required": "approval_pending_for_viable_route",
        "clarification_required": "required_decision_information_missing",
        "validation_required": "validation_needed_before_route_selection",
        "no_execution": "no_surviving_route_after_constraint_filter",
        "context_compaction_required": "context_compaction_required_before_cloud_execution",
        "context_compaction_in_progress": "wait_for_active_compaction_before_cloud_execution",
        "context_reset_required": "context_reset_required_before_route_selection",
        "budget_exhausted": "monthly_cloud_budget_exhausted",
        "quota_exhausted": "cloud_provider_quota_exhausted",
    }.get(decision_state, "alternative_state_required")


def _fallback(
    selected: dict[str, Any] | None,
    discarded_routes: list[dict[str, Any]],
) -> dict[str, Any]:
    if not selected or not selected.get("fallback_for"):
        return {
            "fallback_used": False,
            "preferred_route_id": None,
            "fallback_route_id": None,
            "reason": None,
        }
    preferred_route_id = selected["fallback_for"]
    discarded = {
        route["route_id"]: route["blocked_by"]
        for route in discarded_routes
    }
    if preferred_route_id not in discarded:
        return {
            "fallback_used": False,
            "preferred_route_id": preferred_route_id,
            "fallback_route_id": None,
            "reason": "preferred_route_not_blocked_in_this_snapshot",
        }
    return {
        "fallback_used": True,
        "preferred_route_id": preferred_route_id,
        "fallback_route_id": selected["route_id"],
        "reason": discarded[preferred_route_id],
    }


def _approval_conditions(
    decision_state: str, discarded_routes: list[dict[str, Any]]
) -> list[str]:
    if decision_state == "approval_required":
        return [
            route["route_id"]
            for route in discarded_routes
            if route["blocked_by"] == "approval_required_not_granted"
        ]
    return []


def _validation_conditions(
    request: DecisionRequest,
    decision_state: str,
    selected: dict[str, Any] | None,
) -> list[str]:
    conditions = []
    if request.validation_required:
        conditions.append("manual_review_before_real_execution")
    if decision_state == "validation_required":
        route_id = selected["route_id"] if selected else "no_selected_route"
        conditions.append(f"validation_required_for:{route_id}")
    return conditions


def _execution_cost(selected: dict[str, Any] | None) -> dict[str, Any]:
    if not selected:
        return {"execution_cost_estimate": None, "model_used": None}
    return {
        "execution_cost_estimate": selected["estimated_cloud_cost_usd"],
        "estimated_latency_ms": selected["estimated_latency_ms"],
        "model_used": selected["model_used"],
        "resource_type": selected["resource_type"],
        "tokens_input": None,
        "tokens_output": None,
        "tokens_total": None,
        "cloud_cost_estimate_usd": selected["estimated_cloud_cost_usd"],
        "quota_metered": selected["quota_metered"],
        "monetary_metered": selected["monetary_metered"],
    }


def _projected_context_tokens(request: DecisionRequest) -> int:
    return (
        request.context_current_tokens
        + request.context_estimated_input_tokens
        + request.context_expected_output_tokens
    )


def _context_action(request: DecisionRequest) -> str:
    if request.context_compaction_in_progress:
        return "compaction_in_progress"
    projected = _projected_context_tokens(request)
    if projected >= request.context_reset_at_tokens:
        return "reset_required"
    if request.context_compaction_enabled and projected >= request.context_compact_at_tokens:
        return "compaction_required"
    return "none"


def _remaining_monthly_budget(request: DecisionRequest) -> float:
    return round(
        max(request.monthly_cloud_budget_usd - request.monthly_cloud_spend_usd, 0.0),
        6,
    )


def _quota_observation_applies(request: DecisionRequest, route: CandidateRoute) -> bool:
    return (
        request.cloud_quota_provider_id is None
        or request.cloud_quota_provider_id == route.provider_id
    )


def _quota_cost(request: DecisionRequest, route: CandidateRoute) -> dict[str, Any]:
    if not route.quota_metered:
        return {
            "metered": False,
            "provider_id": route.provider_id,
            "remaining_fraction": None,
            "reset_horizon_ratio": 0.0,
            "context_pressure_ratio": 0.0,
            "preservation_bias": 0.0,
            "penalty": 0.0,
            "source": "local_route_consumes_no_cloud_quota",
        }
    context_pressure = min(
        _projected_context_tokens(request) / max(request.context_hard_limit_tokens, 1),
        1.0,
    )
    scarcity = 1.0 - request.cloud_quota_remaining_fraction
    reset_horizon = (
        request.cloud_quota_reset_after_seconds / request.cloud_quota_window_seconds
        if request.cloud_quota_reset_after_seconds is not None
        and request.cloud_quota_window_seconds is not None
        else 1.0
    )
    preservation_bias = 0.15
    penalty = round(
        preservation_bias
        + 0.45 * scarcity
        + 0.25 * reset_horizon
        + 0.15 * context_pressure,
        6,
    )
    return {
        "metered": True,
        "provider_id": route.provider_id,
        "remaining_fraction": request.cloud_quota_remaining_fraction,
        "reset_after_seconds": request.cloud_quota_reset_after_seconds,
        "window_seconds": request.cloud_quota_window_seconds,
        "reset_horizon_ratio": round(reset_horizon, 6),
        "context_pressure_ratio": round(context_pressure, 6),
        "preservation_bias": preservation_bias,
        "penalty": penalty,
        "source": (
            "trusted_openclaw_quota_observation"
            if request.cloud_quota_provider_id is not None
            else "trusted_compatibility_quota_policy"
        ),
        "quota_values_inferred": False,
        "subscription_quota_converted_to_usd": False,
    }


def _economic_guardrail(
    request: DecisionRequest,
    selected: dict[str, Any] | None,
) -> dict[str, Any]:
    selected_cloud_cost = (
        selected["estimated_cloud_cost_usd"]
        if selected and selected.get("monetary_metered")
        else 0.0
    )
    remaining_before = _remaining_monthly_budget(request)
    return {
        "monthly_cloud_budget_usd": request.monthly_cloud_budget_usd,
        "monthly_cloud_spend_usd": request.monthly_cloud_spend_usd,
        "remaining_before_decision_usd": remaining_before,
        "selected_route_estimated_cloud_cost_usd": selected_cloud_cost,
        "remaining_after_estimate_usd": round(max(remaining_before - selected_cloud_cost, 0.0), 6),
        "cloud_quota_remaining_fraction": request.cloud_quota_remaining_fraction,
        "applies_only_to_monetarily_metered_api": True,
        "budget_period": request.budget_period,
        "cost_is_estimate": True,
        "interactive_configuration": "not_configured",
    }


def _quota_guardrail(
    request: DecisionRequest,
    selected: dict[str, Any] | None,
) -> dict[str, Any]:
    selected_cost = (
        selected.get("quota_cost_evidence")
        if selected and selected.get("quota_metered")
        else None
    )
    return {
        "provider_id": request.cloud_quota_provider_id,
        "remaining_fraction": request.cloud_quota_remaining_fraction,
        "reset_after_seconds": request.cloud_quota_reset_after_seconds,
        "window_seconds": request.cloud_quota_window_seconds,
        "selected_route_consumes_quota": bool(
            selected and selected.get("quota_metered")
        ),
        "selected_route_quota_cost": selected_cost,
        "optimization_objective": "maximize_observed_cloud_quota_preservation",
        "quota_values_inferred": False,
        "subscription_quota_converted_to_usd": False,
    }


def _context_guardrail(request: DecisionRequest) -> dict[str, Any]:
    projected = _projected_context_tokens(request)
    return {
        "current_tokens": request.context_current_tokens,
        "estimated_input_tokens": request.context_estimated_input_tokens,
        "expected_output_tokens": request.context_expected_output_tokens,
        "projected_tokens": projected,
        "compact_at_tokens": request.context_compact_at_tokens,
        "reset_at_tokens": request.context_reset_at_tokens,
        "hard_limit_tokens": request.context_hard_limit_tokens,
        "utilization_ratio": round(projected / request.context_hard_limit_tokens, 6),
        "required_action": _context_action(request),
        "compaction_enabled": request.context_compaction_enabled,
        "compaction_in_progress": request.context_compaction_in_progress,
    }


def _plan_steps(selected: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not selected:
        return []
    return [
        {
            "step_id": "step-001",
            "action": "return_offline_execution_plan",
            "route_id": selected["route_id"],
            "executes_real_action": False,
        }
    ]


def _decision_confidence(
    request: DecisionRequest,
    candidate_routes: list[CandidateRoute],
    discarded_routes: list[dict[str, Any]],
    surviving_routes: list[CandidateRoute],
    routes_evaluated: list[dict[str, Any]],
    routes_not_evaluated: list[dict[str, Any]],
    selected: dict[str, Any] | None,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if not selected:
        return {
            "level": "low",
            "score": 0.2,
            "reasons": ["no_selected_route"],
        }

    reasons = ["selected_route_is_admissible_under_snapshot"]
    score = 0.85
    if discarded_routes:
        score -= 0.1
        reasons.append("some_candidates_blocked_by_constraints")
    if routes_not_evaluated:
        score -= 0.15
        reasons.append("search_space_not_fully_evaluated")
    if request.risk_level in {"high", "critical"}:
        score -= 0.15
        reasons.append("request_risk_requires_caution")
    if fallback["fallback_used"]:
        score -= 0.1
        reasons.append("fallback_used_after_preferred_route_blocked")
    if surviving_routes and len(routes_evaluated) == len(surviving_routes):
        score += 0.05
        reasons.append("all_surviving_routes_evaluated")
    if len(candidate_routes) > 1:
        reasons.append("multiple_candidates_compared")

    score = round(max(min(score, 0.95), 0.1), 2)
    if score >= 0.8:
        level = "high"
    elif score >= 0.5:
        level = "medium"
    else:
        level = "low"
    return {
        "level": level,
        "score": score,
        "reasons": reasons,
    }


def _residual_uncertainty(routes_not_evaluated: list[dict[str, Any]]) -> list[str]:
    uncertainty = [
        "No real provider, model, tool, or OpenClaw runtime execution occurs",
    ]
    if routes_not_evaluated:
        uncertainty.append("Some admissible candidates were not evaluated due to Search Budget or Early Exit")
    return uncertainty


def _explanation(
    selected: dict[str, Any] | None,
    discarded_routes: list[dict[str, Any]],
    decision_state: str,
    fallback: dict[str, Any],
    stop_condition: str,
) -> dict[str, Any]:
    if not selected:
        return {
            "summary": f"Decision ended in {decision_state} under offline v1 hard constraints.",
            "why_selected": None,
            "why_discarded": discarded_routes,
            "final_state": decision_state,
            "stop_condition": stop_condition,
        }
    reason = "lowest deterministic global cost after hard constraints within Search Budget"
    if fallback["fallback_used"]:
        reason = "fallback route selected because the preferred route was blocked"
    return {
        "summary": "Selected an admissible governed route under the active reproducible snapshot.",
        "why_selected": {
            "route_id": selected["route_id"],
            "reason": reason,
        },
        "why_discarded": discarded_routes,
        "final_state": decision_state,
        "fallback": fallback,
        "stop_condition": stop_condition,
        "governance": "blocked routes did not compete for ranking",
    }


def _different_decision_conditions(discarded_routes: list[dict[str, Any]]) -> list[str]:
    conditions = [route["reconsider_if"] for route in discarded_routes]
    if not conditions:
        conditions.append("different registry snapshot or policy snapshot changes candidate metadata")
    return sorted(set(conditions))


def _has_tie(ranked_routes: list[dict[str, Any]]) -> bool:
    if len(ranked_routes) < 2:
        return False
    return ranked_routes[0]["global_cost"] == ranked_routes[1]["global_cost"]


def _reproducibility_snapshot(
    request: DecisionRequest,
    registry: CapabilityRegistry,
    candidate_routes: list[CandidateRoute],
    effective_profile: str,
) -> dict[str, Any]:
    snapshot = {
        "request": request.normalized(),
        "registry_snapshot_id": registry.snapshot_id,
        "policy_snapshot_id": registry.policy_snapshot_id,
        "configuration_snapshot_id": registry.configuration_snapshot_id,
        "profile_used": effective_profile,
        "profile_weights": PROFILE_WEIGHTS[effective_profile],
        "candidate_metadata": [route.as_evidence() for route in candidate_routes],
    }
    snapshot["snapshot_digest"] = _digest(snapshot)
    return snapshot


def _decision_id(
    reproducibility_snapshot: dict[str, Any],
    selected: dict[str, Any] | None,
    decision_state: str,
) -> str:
    source = {
        "reproducibility_snapshot_digest": reproducibility_snapshot["snapshot_digest"],
        "selected_route": selected["route_id"] if selected else None,
        "decision_state": decision_state,
    }
    return f"acce-decision-{_digest(source)[:16]}"


def _digest(source: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(source, sort_keys=True).encode("utf-8")).hexdigest()
