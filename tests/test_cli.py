from __future__ import annotations

import json
from pathlib import Path

import pytest

from acce_optimizer.cli import main
from acce_optimizer.core.engine import DecisionRequest
from acce_optimizer.core.registry import CapabilityRegistry


def test_run_decision_requires_request_and_registry(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--run-decision"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "missing required input: --request, --registry" in captured.err
    assert "Traceback" not in captured.err


def test_repository_examples_are_valid_runtime_inputs() -> None:
    root = Path(__file__).resolve().parents[1]

    request = json.loads((root / "examples" / "request.json").read_text())
    registry = json.loads((root / "examples" / "registry.json").read_text())

    parsed_request = DecisionRequest.from_mapping(request)
    parsed_registry = CapabilityRegistry(registry)

    assert parsed_request.request_id == "example-request-001"
    assert parsed_request.required_capabilities == ("text-generation",)
    assert parsed_registry.snapshot["snapshot_id"] == "example-registry-001"
    assert len(parsed_registry.candidates_for("text-generation")) == 1
