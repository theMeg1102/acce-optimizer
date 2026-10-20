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
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .io import read_json
from .models import DecisionRequest
from .registry import CapabilityRegistry
from .runtime import DecisionService

MAX_BODY_BYTES = 256 * 1024


def _load_registry(registry_path: Path, observations_path: Path) -> CapabilityRegistry:
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
    if changed:
        # Make the evidence-dependent registry view visible to deterministic IDs.
        fingerprint = hashlib.sha256(
            json.dumps(observations, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        snapshot["snapshot_id"] = f"{snapshot.get('snapshot_id', 'registry')}-evidence-{fingerprint}"
    return CapabilityRegistry(snapshot)


def _store_observations(payload: Any, observations_path: Path) -> dict[str, int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("snapshot"), dict):
        raise ValueError("snapshot must be a JSON object")
    accepted: dict[str, dict[str, Any]] = {}
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
        accepted[f"{provider.strip().lower()}/{model_id.strip()}"] = {
            "latency_ms": int(round(latency)),
            "captured_at": telemetry.get("capturedAt"),
            "measurement_id": telemetry.get("measurementId"),
        }
    observations_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = observations_path.with_suffix(observations_path.suffix + ".tmp")
    temporary.write_text(json.dumps(accepted, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(observations_path)
    return {"accepted": len(accepted)}
    
def _decision(payload: Any, registry_path: Path, observations_path: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    request = payload.get("request")
    if not isinstance(request, dict):
        raise ValueError("request field must be a JSON object")
    registry = _load_registry(registry_path, observations_path)
    result = DecisionService(registry=registry).decide(DecisionRequest.from_mapping(request))
    selected = result.get("selected_route")
    if not isinstance(selected, dict):
        return {
            "decision_id": result.get("decision_id"),
            "decision_state": result.get("decision_state"),
            "status": result.get("status"),
            "selected_route": None,
            "providerOverride": None,
            "modelOverride": None,
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
        "providerOverride": selected.get("provider_id"),
        "modelOverride": selected.get("model_used"),
        "engine": result.get("decision_engine"),
        "registry_snapshot_id": result.get("registry_snapshot_id"),
        "policy_snapshot_id": result.get("policy_snapshot_id"),
    }


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
            if route_path not in {"/v1/decide", "/v1/observations"}:
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
                else:
                    self._send(200, _decision(payload, registry_path, observations_path))
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
