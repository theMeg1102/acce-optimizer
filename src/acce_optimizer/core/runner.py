from __future__ import annotations

from pathlib import Path

from .io import read_json
from .models import DecisionRequest
from .runtime import DecisionService


def run_fixture(request_path: Path, registry_path: Path, decision_log_path: Path | None) -> dict:
    request = DecisionRequest.from_mapping(read_json(request_path))
    service = DecisionService.from_paths(
        registry_path=registry_path,
        decision_log_path=decision_log_path,
    )
    return service.decide(request)
