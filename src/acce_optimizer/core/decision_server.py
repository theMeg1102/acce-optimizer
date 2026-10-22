from __future__ import annotations

"""Small, dependency-free HTTP bridge for the existing ACCE DecisionService.

Run on a trusted private interface. The server never accepts a registry from
clients: it loads the operator-managed registry and delegates every decision to
the canonical Python graph engine.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .io import read_json
from .models import DecisionRequest
from .registry import CapabilityRegistry
from .runtime import DecisionService, QuotaPolicy
from .trusted_state import MonthlyUsageLedger, TrustedRuntimeState

MAX_BODY_BYTES = 256 * 1024


def _load_registry(registry_path: Path, observations_path: Path, *, require_production: bool = True, route_outcomes_path: Path | None = None, task_signature: str | None = None) -> CapabilityRegistry:
    # Re-read the operator-owned registry and measured evidence for each decision.
    snapshot = read_json(registry_path)
    observations: dict[str, Any] = {}
    if observations_path.is_file():
        loaded = read_json(observations_path)
        if isinstance(loaded, dict):
            observations = loaded

    changed = False
    for route in snapshot.get("instances", []):
        if not isinstance(route, dict):
            continue
        key = f"{str(route.get('provider_id', '')).strip().lower()}/{str(route.get('model_used', '')).strip()}"
        evidence = observations.get(key)
        if not isinstance(evidence, dict):
            continue
        latency = evidence.get("latency_ms")
        if isinstance(latency, (int, float)) and not isinstance(latency, bool) and 0 <= latency <= 120000:
            route["estimated_latency_ms"] = int(round(latency))
            changed = True
        context_budget = evidence.get("context_window_tokens")
        if isinstance(context_budget, int) and not isinstance(context_budget, bool) and context_budget > 0:
            current_context = route.get("context_window_tokens")
            route["context_window_tokens"] = min(current_context, context_budget) if isinstance(current_context, int) and not isinstance(current_context, bool) and current_context > 0 else context_budget
            changed = True
    if changed:
        # Make the evidence-dependent registry view visible to deterministic IDs.
        fingerprint = hashlib.sha256(
            json.dumps(observations, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        snapshot["snapshot_id"] = f"{snapshot.get('snapshot_id', 'registry')}-evidence-{fingerprint}"

    # Route outcomes are reliability evidence, never quality or preference.
    # Use only outcomes for the current normalized task signature and only after
    # five observations; shrink the observed rate toward the registry's quality
    # prior to avoid overreacting to small samples.
    if route_outcomes_path is not None and task_signature:
        try:
            raw_outcomes = json.loads(route_outcomes_path.read_text(encoding="utf-8")) if route_outcomes_path.is_file() else []
        except Exception:
            raw_outcomes = []
        if isinstance(raw_outcomes, list):
            grouped: dict[str, list[bool]] = {}
            for item in raw_outcomes[-2000:]:
                if not isinstance(item, dict) or item.get("task_signature") != task_signature:
                    continue
                route_id = item.get("route_id")
                outcome = item.get("outcome")
                if isinstance(route_id, str) and outcome in {"success", "failure"}:
                    grouped.setdefault(route_id, []).append(outcome == "success")
            for route in snapshot.get("instances", []):
                if not isinstance(route, dict):
                    continue
                outcomes = grouped.get(route.get("route_id"), [])
                if len(outcomes) < 5:
                    continue
                prior = route.get("quality_score", 0.5)
                if isinstance(prior, bool) or not isinstance(prior, (int, float)) or not 0 <= prior <= 1:
                    prior = 0.5
                successes = sum(outcomes)
                route["observed_success_rate"] = (successes + 5 * prior) / (len(outcomes) + 5)
                route["observed_sample_count"] = len(outcomes)
            if grouped:
                fingerprint = hashlib.sha256(
                    json.dumps({key: values[-2000:] for key, values in sorted(grouped.items())}, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()[:12]
                snapshot["snapshot_id"] = f"{snapshot.get('snapshot_id', 'registry')}-outcomes-{fingerprint}"
    return CapabilityRegistry.from_production_snapshot(snapshot) if require_production else CapabilityRegistry(snapshot)


def _store_observations(payload: Any, observations_path: Path) -> dict[str, int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("snapshot"), dict):
        raise ValueError("snapshot must be a JSON object")
    accepted: dict[str, dict[str, Any]] = {}
    if observations_path.is_file():
        try:
            existing = read_json(observations_path)
            if isinstance(existing, dict):
                accepted.update({key: value for key, value in existing.items() if isinstance(key, str) and isinstance(value, dict)})
        except Exception:
            accepted = {}
    for key, model in payload["snapshot"].items():
        if not isinstance(key, str) or not isinstance(model, dict):
            continue
        if model.get("productionEligible") is not False or model.get("telemetryStatus") != "captured":
            continue
        provider = model.get("providerId")
        model_id = model.get("modelId")
        telemetry = model.get("telemetry")
        metrics = telemetry.get("metrics") if isinstance(telemetry, dict) else None
        if not isinstance(provider, str) or not provider.strip() or not isinstance(model_id, str) or not model_id.strip():
            continue
        if not isinstance(metrics, dict):
            continue
        latency = metrics.get("latencyMs")
        if isinstance(latency, bool) or not isinstance(latency, (int, float)) or not 0 <= latency <= 120000:
            continue
        record = {
            "latency_ms": int(round(latency)),
            "captured_at": telemetry.get("capturedAt"),
            "measurement_id": telemetry.get("measurementId"),
        }
        key = f"{provider.strip().lower()}/{model_id.strip()}"
        context_budget = metrics.get("contextTokenBudget")
        if isinstance(context_budget, int) and not isinstance(context_budget, bool) and 0 < context_budget <= 1_000_000:
            record["context_window_tokens"] = context_budget
        else:
            previous = accepted.get(key)
            if isinstance(previous, dict) and isinstance(previous.get("context_window_tokens"), int):
                record["context_window_tokens"] = previous["context_window_tokens"]
        accepted[key] = record
    accepted = dict(list(accepted.items())[-500:])
    observations_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(observations_path.parent, 0o700)
    temporary = observations_path.with_suffix(observations_path.suffix + ".tmp")
    temporary.write_text(json.dumps(accepted, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(observations_path)
    return {"accepted": len(accepted)}
    
def _load_trusted_state() -> TrustedRuntimeState | None:
    telemetry_raw = os.environ.get("ACCE_TRUSTED_STATE_TELEMETRY_PATH", "").strip()
    ledger_raw = os.environ.get("ACCE_USAGE_LEDGER_PATH", "").strip()
    if not telemetry_raw or not ledger_raw:
        return None
    telemetry_path = Path(telemetry_raw).expanduser().resolve()
    ledger_path = Path(ledger_raw).expanduser().resolve()
    if not telemetry_path.is_file() or not ledger_path.is_file():
        return None
    budget = float(os.environ.get("ACCE_MONTHLY_CLOUD_BUDGET_USD", "20"))
    period = os.environ.get("ACCE_BUDGET_PERIOD", "").strip() or datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        ledger = MonthlyUsageLedger(ledger_path, period=period, budget_usd=budget)
        return TrustedRuntimeState.from_files(ledger=ledger, telemetry_path=telemetry_path)
    except Exception:
        # Stale or malformed trusted observations must fail closed to local-only.
        return None


def _apply_runtime_catalog(registry: CapabilityRegistry, request: dict[str, Any], runtime_catalog: Any) -> CapabilityRegistry:
    """Intersect the validated operator registry with OpenClaw's live catalog.

    OpenClaw supplies runtime configuration facts; ACCE still owns route
    authorization and ranking. This function can remove routes but never add
    or authorize one. Runtime prices are used only with explicit positive token
    estimates and complete input/output price metadata.
    """
    allowed_pairs: set[tuple[str, str]] = set()
    runtime_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(runtime_catalog, list):
        for item in runtime_catalog:
            if not isinstance(item, dict):
                continue
            provider_id = item.get("providerId")
            model_id = item.get("modelId")
            if isinstance(provider_id, str) and provider_id.strip() and isinstance(model_id, str) and model_id.strip():
                pair = (provider_id.strip(), model_id.strip())
                allowed_pairs.add(pair)
                runtime_by_pair[pair] = item

    request_context = request.get("context") if isinstance(request.get("context"), dict) else {}
    request_tokens_in = request.get("context_estimated_input_tokens", request_context.get("estimated_input_tokens", 0))
    request_tokens_out = request.get("context_expected_output_tokens", request_context.get("expected_output_tokens", 0))
    valid_token_estimates = (
        isinstance(request_tokens_in, int) and not isinstance(request_tokens_in, bool) and request_tokens_in > 0
        and isinstance(request_tokens_out, int) and not isinstance(request_tokens_out, bool) and request_tokens_out > 0
    )
    snapshot = registry.snapshot
    filtered_routes = []
    for route in snapshot.get("instances", []):
        if not isinstance(route, dict):
            continue
        pair = (route.get("provider_id"), route.get("model_used"))
        if pair not in allowed_pairs:
            continue
        runtime_model = runtime_by_pair[pair]
        # OpenClaw's effective context cap is a hard runtime constraint.
        # Use the more conservative of the governed registry and configured
        # runtime cap; never enlarge the operator's admitted context window.
        runtime_context = runtime_model.get("contextTokens")
        if not isinstance(runtime_context, (int, float)) or isinstance(runtime_context, bool) or runtime_context <= 0:
            runtime_context = runtime_model.get("contextWindow")
        if isinstance(runtime_context, (int, float)) and not isinstance(runtime_context, bool) and runtime_context > 0:
            governed_context = route.get("context_window_tokens")
            route["context_window_tokens"] = (
                min(governed_context, int(runtime_context))
                if isinstance(governed_context, int) and not isinstance(governed_context, bool) and governed_context > 0
                else int(runtime_context)
            )
        # OpenClaw prices are USD per million tokens. Missing prices or token
        # estimates preserve the registry estimate; they are never treated as $0.
        cost = runtime_model.get("cost")
        input_price = cost.get("input") if isinstance(cost, dict) else None
        output_price = cost.get("output") if isinstance(cost, dict) else None
        cache_pricing_unmodeled = isinstance(cost, dict) and any(
            isinstance(cost.get(field), (int, float))
            and not isinstance(cost.get(field), bool)
            and cost.get(field) > 0
            for field in ("cacheRead", "cacheWrite")
        )
        if (
            valid_token_estimates
            and not cache_pricing_unmodeled
            and isinstance(input_price, (int, float)) and not isinstance(input_price, bool) and input_price >= 0
            and isinstance(output_price, (int, float)) and not isinstance(output_price, bool) and output_price >= 0
        ):
            route["estimated_cloud_cost_usd"] = (request_tokens_in * input_price + request_tokens_out * output_price) / 1_000_000
            route["monetary_metered"] = True
        filtered_routes.append(route)

    snapshot["instances"] = filtered_routes
    catalog_fingerprint = hashlib.sha256(
        json.dumps(sorted(allowed_pairs), separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    snapshot["snapshot_id"] = f"{snapshot.get('snapshot_id', 'registry')}-runtime-{catalog_fingerprint}"
    # The source registry has already passed its strict production contract.
    return CapabilityRegistry(snapshot)


def _decision(payload: Any, registry_path: Path, observations_path: Path, *, require_production: bool = True, route_outcomes_path: Path | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    request = payload.get("request")
    if not isinstance(request, dict):
        raise ValueError("request field must be a JSON object")
    task_signature = payload.get("task_signature") if isinstance(payload.get("task_signature"), str) else None
    registry = _load_registry(registry_path, observations_path, require_production=require_production, route_outcomes_path=route_outcomes_path, task_signature=task_signature)
    if "runtime_catalog" in payload:
        registry = _apply_runtime_catalog(registry, request, payload.get("runtime_catalog"))
    # A preference is a soft ranking signal only. Resolve it to an exact route
    # already present in the operator-authorized, runtime-filtered registry.
    preference = payload.get("preference")
    if isinstance(preference, dict):
        preferred_provider = preference.get("providerId")
        preferred_model = preference.get("modelId")
        if isinstance(preferred_provider, str) and isinstance(preferred_model, str):
            preferred = next((route for route in registry.snapshot.get("instances", [])
                              if isinstance(route, dict)
                              and route.get("provider_id") == preferred_provider
                              and route.get("model_used") == preferred_model), None)
            if preferred is not None:
                request = dict(request)
                request["preferred_route_id"] = preferred.get("route_id")
    preferred_order = payload.get("preferred_route_order")
    if isinstance(preferred_order, list):
        authorized_route_ids = {
            route.get("route_id") for route in registry.snapshot.get("instances", [])
            if isinstance(route, dict) and isinstance(route.get("route_id"), str)
        }
        request = dict(request)
        request["preferred_route_order"] = [
            route_id for route_id in preferred_order
            if isinstance(route_id, str) and route_id in authorized_route_ids
        ][:100]
    trusted_state = _load_trusted_state()
    request_data = dict(request)
    constraints = request_data.get("constraints")
    constraints = dict(constraints) if isinstance(constraints, dict) else {}
    if trusted_state is None:
        # Do not invent live quota, spend, or context telemetry. Without a fresh
        # trusted state snapshot, explicitly disallow external routes and cloud cost.
        constraints["external_network_allowed"] = False
        constraints["max_cloud_cost_usd"] = 0
    request_data["constraints"] = constraints
    decision_log_raw = os.environ.get("ACCE_DECISION_LOG_PATH", "").strip()
    decision_log_path = Path(decision_log_raw).expanduser().resolve() if decision_log_raw else None
    service = (
        DecisionService(registry=registry, decision_log_path=decision_log_path, trusted_state=trusted_state)
        if trusted_state is not None
        else DecisionService(
            registry=registry,
            decision_log_path=decision_log_path,
            quota_policy=QuotaPolicy(remaining_fraction=0.0),
        )
    )
    result = service.adaptive_decision(DecisionRequest.from_mapping(request_data))
    result["policy_mode"] = "trusted_state" if trusted_state is not None else "local_only_no_trusted_state"
    selected = result.get("selected_route")
    # Only an actual governed adaptive-graph selection may override OpenClaw.
    # The compatibility plan is returned for diagnosis/fallback, not applied.
    if result.get("decision_engine") != "adaptive_graph" or result.get("routing_applied") is not True:
        selected = None
    if not isinstance(selected, dict):
        return {
            "decision_id": result.get("decision_id"),
            "decision_state": result.get("decision_state"),
            "status": result.get("status"),
            "selected_route": None,
            "ranking_result": result.get("ranking_result", []),
            "providerOverride": None,
            "modelOverride": None,
            "policy_mode": result.get("policy_mode"),
        }
    return {
        "decision_id": result.get("decision_id"),
        "decision_state": result.get("decision_state"),
        "status": result.get("status"),
        "selected_route": {
            "route_id": selected.get("route_id"),
            "provider_id": selected.get("provider_id"),
            "model_used": selected.get("model_used"),
        },
        "ranking_result": result.get("ranking_result", []),
        "providerOverride": selected.get("provider_id"),
        "modelOverride": selected.get("model_used"),
        "engine": result.get("decision_engine"),
        "registry_snapshot_id": result.get("registry_snapshot_id"),
        "policy_snapshot_id": result.get("policy_snapshot_id"),
        "policy_mode": result.get("policy_mode"),
    }


def _store_route_outcome(payload: Any, registry_path: Path, outcomes_path: Path, *, require_production: bool = True) -> dict[str, int]:
    """Persist bounded, minimized route-level run outcomes for the existing graph."""
    if not isinstance(payload, dict):
        raise ValueError("outcome must be an object")
    route_id = payload.get("route_id")
    provider_id = payload.get("provider_id")
    model_id = payload.get("model_id")
    task_signature = payload.get("task_signature")
    outcome = payload.get("outcome")
    decision_id = payload.get("decision_id")
    if not all(isinstance(value, str) and value.strip() for value in (route_id, provider_id, model_id, task_signature)):
        raise ValueError("route_id, provider_id, model_id, and task_signature are required")
    if len(route_id) > 128 or len(provider_id) > 128 or len(model_id) > 256 or len(task_signature) > 256:
        raise ValueError("outcome identifiers exceed limits")
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_|-." for char in task_signature):
        raise ValueError("task_signature contains unsupported characters")
    if outcome not in {"success", "failure"}:
        raise ValueError("outcome must be success or failure")
    if decision_id is not None and (not isinstance(decision_id, str) or len(decision_id) > 128):
        raise ValueError("decision_id is invalid")

    registry_snapshot = read_json(registry_path)
    registry = CapabilityRegistry.from_production_snapshot(registry_snapshot) if require_production else CapabilityRegistry(registry_snapshot)
    authorized = any(
        isinstance(route, dict)
        and route.get("route_id") == route_id
        and route.get("provider_id") == provider_id
        and route.get("model_used") == model_id
        for route in registry.snapshot.get("instances", [])
    )
    if not authorized:
        raise ValueError("outcome route is not present in the operator-authorized registry")

    outcomes: list[dict[str, Any]] = []
    if outcomes_path.is_file():
        try:
            existing = json.loads(outcomes_path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                outcomes = [item for item in existing if isinstance(item, dict)]
        except Exception:
            outcomes = []
    outcomes.append({
        "route_id": route_id,
        "provider_id": provider_id,
        "model_id": model_id,
        "task_signature": task_signature,
        "outcome": outcome,
        "decision_id": decision_id if isinstance(decision_id, str) else None,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    })
    outcomes = outcomes[-2000:]
    outcomes_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(outcomes_path.parent, 0o700)
    temporary = outcomes_path.with_suffix(outcomes_path.suffix + ".tmp")
    temporary.write_text(json.dumps(outcomes, separators=(",", ":"), allow_nan=False) + chr(10), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(outcomes_path)
    return {"accepted": 1, "retained": len(outcomes)}


def make_handler(registry_path: Path, observations_path: Path, bearer_token: str | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ACCE-DecisionBridge/1.0"

        def log_message(self, _format: str, *_args: Any) -> None:
            # Avoid logging request payloads or session/prompt data.
            return

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            if urlparse(self.path).path == "/health":
                self._send(200, {"status": "ok", "engine": "DecisionService", "contract": "1.4.0"})
            else:
                self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:
            route_path = urlparse(self.path).path
            if route_path not in {"/v1/decide", "/v1/observations", "/v1/outcomes"}:
                self._send(404, {"error": "not_found"})
                return
            if bearer_token and self.headers.get("Authorization") != f"Bearer {bearer_token}":
                self._send(401, {"error": "unauthorized"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > MAX_BODY_BYTES:
                    self._send(413, {"error": "invalid_body_size"})
                    return
                raw = self.rfile.read(size)
                payload = json.loads(raw.decode("utf-8"))
                if route_path == "/v1/observations":
                    self._send(200, _store_observations(payload, observations_path))
                elif route_path == "/v1/outcomes":
                    outcomes_raw = os.environ.get("ACCE_ROUTE_OUTCOMES_PATH", "").strip()
                    outcomes_path = Path(outcomes_raw).expanduser().resolve() if outcomes_raw else registry_path.with_name("acce-route-outcomes.json")
                    self._send(200, _store_route_outcome(payload, registry_path, outcomes_path))
                else:
                    outcomes_raw = os.environ.get("ACCE_ROUTE_OUTCOMES_PATH", "").strip()
                    outcomes_path = Path(outcomes_raw).expanduser().resolve() if outcomes_raw else registry_path.with_name("acce-route-outcomes.json")
                    self._send(200, _decision(payload, registry_path, observations_path, route_outcomes_path=outcomes_path))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
                self._send(400, {"error": "invalid_request", "detail": str(error)})
            except Exception as error:
                # Keep server internals and registry contents out of HTTP responses.
                self._send(422, {"error": "decision_failed", "detail": str(error)})

    return Handler


def main() -> None:
    registry_raw = os.environ.get("ACCE_REGISTRY_PATH", "").strip()
    if not registry_raw:
        raise SystemExit("ACCE_REGISTRY_PATH must point to an operator-managed registry JSON")
    registry_path = Path(registry_raw).expanduser().resolve()
    if not registry_path.is_file():
        raise SystemExit(f"ACCE registry file does not exist: {registry_path}")
    host = os.environ.get("ACCE_DECISION_BIND", "127.0.0.1")
    port = int(os.environ.get("ACCE_DECISION_PORT", "18791"))
    token = os.environ.get("ACCE_DECISION_TOKEN", "").strip() or None
    observations_raw = os.environ.get("ACCE_OBSERVATIONS_PATH", "").strip()
    observations_path = (
        Path(observations_raw).expanduser().resolve()
        if observations_raw
        else registry_path.with_name("acce-discovery-observations.json")
    )
    if host not in {"127.0.0.1", "::1", "localhost"} and not token:
        raise SystemExit("ACCE_DECISION_TOKEN is required when binding beyond loopback")
    server = ThreadingHTTPServer((host, port), make_handler(registry_path, observations_path, token))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
