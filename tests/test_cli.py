from __future__ import annotations

import pytest

from acce_optimizer.cli import main


def test_run_decision_requires_request_and_registry(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--run-decision"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "missing required input: --request, --registry" in captured.err
    assert "Traceback" not in captured.err
