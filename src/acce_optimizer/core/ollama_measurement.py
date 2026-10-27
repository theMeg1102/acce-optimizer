from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .errors import ContractValidationError


MeasurementTransport = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]

_SYNTHETIC_PROMPT = (
    "This is an automated local availability check. "
    "Return exactly AURORA_OK and nothing else."
)
_EXPECTED_RESPONSE = "AURORA_OK"


def _validated_loopback_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise ContractValidationError(
            "Ollama measurement endpoint must be an unauthenticated loopback HTTP URL"
        )
    try:
        is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        is_loopback = parsed.hostname.casefold() == "localhost"
    if not is_loopback:
        raise ContractValidationError(
            "Ollama measurement endpoint must resolve explicitly to loopback"
        )
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ContractValidationError("Ollama measurement endpoint must not include a path")
    return endpoint.rstrip("/")


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractValidationError(f"Ollama response {field} must be a non-negative integer")
    return value


def _metric_sample(response: Mapping[str, Any], phase: str) -> dict[str, Any]:
    total_duration = _positive_integer(response.get("total_duration"), "total_duration")
    load_duration = _positive_integer(response.get("load_duration"), "load_duration")
    prompt_count = _positive_integer(response.get("prompt_eval_count"), "prompt_eval_count")
    prompt_duration = _positive_integer(
        response.get("prompt_eval_duration"), "prompt_eval_duration"
    )
    eval_count = _positive_integer(response.get("eval_count"), "eval_count")
    eval_duration = _positive_integer(response.get("eval_duration"), "eval_duration")
    raw_text = response.get("response")
    if not isinstance(raw_text, str):
        raise ContractValidationError("Ollama response response must be a string")
    normalized = raw_text.strip()
    tokens_per_second = (
        round(eval_count / (eval_duration / 1_000_000_000), 3)
        if eval_count and eval_duration
        else 0.0
    )
    if not math.isfinite(tokens_per_second):
        raise ContractValidationError("Ollama response produced a non-finite throughput")
    return {
        "phase": phase,
        "total_duration_ms": round(total_duration / 1_000_000, 3),
        "load_duration_ms": round(load_duration / 1_000_000, 3),
        "prompt_eval_count": prompt_count,
        "prompt_eval_duration_ms": round(prompt_duration / 1_000_000, 3),
        "eval_count": eval_count,
        "eval_duration_ms": round(eval_duration / 1_000_000, 3),
        "output_tokens_per_second": tokens_per_second,
        "expected_response_observed": normalized == _EXPECTED_RESPONSE,
        "response_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    }


class OllamaMeasurementClient:
    """Bounded, local-only collection of declared metadata and runtime metrics."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:11434",
        *,
        transport: MeasurementTransport | None = None,
    ) -> None:
        self.endpoint = _validated_loopback_endpoint(endpoint)
        self._transport = transport or self._http_transport

    def _http_transport(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        request = Request(
            self.endpoint + path,
            data=json.dumps(dict(payload)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=300) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ContractValidationError(f"Ollama measurement request failed: {error}") from error
        if not isinstance(decoded, Mapping):
            raise ContractValidationError("Ollama measurement response must be an object")
        return decoded

    def _call(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        response = self._transport(path, payload)
        if not isinstance(response, Mapping):
            raise ContractValidationError("Ollama measurement transport must return an object")
        return response

    def _unload(self, model: str) -> None:
        self._call(
            "/api/generate",
            {"model": model, "prompt": "", "stream": False, "keep_alive": 0},
        )

    def _generate(self, model: str) -> Mapping[str, Any]:
        return self._call(
            "/api/generate",
            {
                "model": model,
                "prompt": _SYNTHETIC_PROMPT,
                "stream": False,
                "think": False,
                "keep_alive": "5m",
                "options": {
                    "num_predict": 32,
                    "seed": 42,
                    "temperature": 0,
                },
            },
        )

    def measure_model(self, model: str) -> dict[str, Any]:
        if not isinstance(model, str) or not model.strip() or "/" in model:
            raise ContractValidationError(
                "Ollama measurement model must be an exact unqualified Ollama model name"
            )
        declared = self._call("/api/show", {"model": model})
        capabilities = declared.get("capabilities", [])
        details = declared.get("details", {})
        if not isinstance(capabilities, list) or any(
            not isinstance(item, str) for item in capabilities
        ):
            raise ContractValidationError("Ollama show capabilities must be a list of strings")
        if not isinstance(details, Mapping):
            raise ContractValidationError("Ollama show details must be an object")

        self._unload(model)
        cold = _metric_sample(self._generate(model), "cold")
        warm = _metric_sample(self._generate(model), "warm")
        self._unload(model)
        return {
            "model_ref": f"ollama/{model}",
            "declared_metadata": {
                "capabilities": sorted(capabilities),
                "family": details.get("family"),
                "parameter_size": details.get("parameter_size"),
                "quantization_level": details.get("quantization_level"),
            },
            "samples": [cold, warm],
            "routing_status_changed": False,
        }

    def measure_inventory(self, models: Sequence[str]) -> dict[str, Any]:
        if not models:
            raise ContractValidationError("at least one Ollama model must be measured")
        if len(set(models)) != len(models):
            raise ContractValidationError("Ollama measurement model names must be unique")
        results = [self.measure_model(model) for model in models]
        return {
            "schema_version": "1.0.0",
            "status": "ollama_local_measurement_complete",
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "endpoint_scope": "loopback_only",
            "prompt_class": "fixed_synthetic_non_user_data",
            "model_count": len(results),
            "models": results,
            "cloud_requests_made": False,
            "openclaw_configuration_changed": False,
            "routing_status_changed": False,
        }
