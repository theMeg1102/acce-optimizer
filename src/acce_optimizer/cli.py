from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from acce_optimizer.core.acceptance import run_acceptance
from acce_optimizer.core.io import stable_json
from acce_optimizer.core.models import DecisionRequest
from acce_optimizer.core.ollama_measurement import OllamaMeasurementClient
from acce_optimizer.core.openclaw_adapter import OpenClawStatusAdapter
from acce_optimizer.core.registry import CapabilityRegistry, validate_production_registry
from acce_optimizer.core.runner import run_fixture
from acce_optimizer.core.runtime import (
    DecisionService,
    EconomicPolicy,
    QuotaPolicy,
    runtime_contract,
)


def build_self_check() -> dict:
    return {
        "system": "acce-adaptive-routing",
        "version": __version__,
        "namespace": "acce_optimizer.core",
        "compatibility_entrypoint": "acce_optimizer",
        "phase": "Adaptive Model Routing Validation",
        "status": "adaptive_shadow_ready_production_routing_disabled",
        "runtime_mode": "offline_reusable_runtime",
        "public_contract": "DecisionService.decide(request)",
        "contract_id": DecisionService.contract_id,
        "contract_version": DecisionService.contract_version,
        "adaptive_shadow": "read_only",
        "adaptive_graph": "immutable",
        "search_algorithms": ["dijkstra", "astar"],
        "governance_before_search": True,
        "resource_state": "immutable_quota_budget_snapshot",
        "learning": "evidence_and_similarity_gated_preferences",
        "openclaw_integration": "read_only_observation_boundary",
        "openclaw_session_mutation": False,
        "production_routing": "disabled",
        "model_execution_by_shadow": False,
        "conversation_content_recorded_by_shadow": False,
        "quota_values_inferred": False,
        "subscription_quota_converted_to_usd": False,
        "available_commands": [
            "--self-check",
            "--runtime-contract",
            "--run-fixture",
            "--run-acceptance",
            "--run-adaptive-shadow",
            "--validate-production-registry",
            "--measure-ollama",
            "--observe-openclaw-status",
        ],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acce")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--runtime-contract", action="store_true")
    parser.add_argument("--run-fixture", action="store_true")
    parser.add_argument("--run-acceptance", action="store_true")
    parser.add_argument("--run-adaptive-shadow", action="store_true")
    parser.add_argument("--validate-production-registry", action="store_true")
    parser.add_argument("--measure-ollama", action="store_true")
    parser.add_argument("--observe-openclaw-status", action="store_true")
    parser.add_argument("--openclaw-status-input", default="-")
    parser.add_argument("--openclaw-session-key")
    parser.add_argument("--safe-status-output", type=Path)
    parser.add_argument("--ollama-endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--ollama-model", action="append", default=[])
    parser.add_argument("--measurement-output", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--decision-log", type=Path)
    parser.add_argument(
        "--regression-manifest",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--acceptance-report",
        type=Path,
        default=None,
    )
    parser.add_argument("--quota-remaining", type=float, default=1.0)
    parser.add_argument("--monthly-budget-usd", type=float, default=20.0)
    parser.add_argument("--monthly-spend-usd", type=float, default=0.0)
    parser.add_argument("--write-evidence", action="store_true")
    args = parser.parse_args(argv)

    def require_files(*paths: Path | None) -> None:
        missing = ["<required path>" if path is None else str(path) for path in paths if path is None or not path.is_file()]
        if missing:
            parser.error("required input file(s) not found: " + ", ".join(missing))

    if args.self_check:
        print(stable_json(build_self_check()))
        return 0

    if args.runtime_contract:
        print(stable_json(runtime_contract()))
        return 0

    if args.validate_production_registry:
        require_files(args.registry)
        data = json.loads(args.registry.read_text(encoding="utf-8"))
        print(stable_json(validate_production_registry(data)))
        return 0

    if args.measure_ollama:
        if not args.ollama_model:
            parser.error("--measure-ollama requires at least one --ollama-model")
        report = OllamaMeasurementClient(args.ollama_endpoint).measure_inventory(args.ollama_model)
        rendered = stable_json(report)
        if args.measurement_output:
            args.measurement_output.parent.mkdir(parents=True, exist_ok=True)
            args.measurement_output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0

    if args.observe_openclaw_status:
        if not args.openclaw_session_key:
            parser.error("--observe-openclaw-status requires --openclaw-session-key")
        if args.openclaw_status_input == "-":
            payload = json.load(sys.stdin)
        else:
            status_path = Path(args.openclaw_status_input)
            require_files(status_path)
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        evidence = OpenClawStatusAdapter.observe(
            payload,
            session_key=args.openclaw_session_key,
        ).as_safe_evidence()
        rendered = stable_json(evidence)
        if args.safe_status_output:
            args.safe_status_output.parent.mkdir(parents=True, exist_ok=True)
            args.safe_status_output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0

    if args.run_adaptive_shadow:
        require_files(args.request, args.registry)
        request = DecisionRequest.from_mapping(
            json.loads(args.request.read_text(encoding="utf-8"))
        )
        service = DecisionService.from_paths(
            args.registry,
            economic_policy=EconomicPolicy(
                monthly_cloud_budget_usd=args.monthly_budget_usd,
                monthly_cloud_spend_usd=args.monthly_spend_usd,
                cloud_quota_remaining_fraction=args.quota_remaining,
            ),
            quota_policy=QuotaPolicy(
                remaining_fraction=args.quota_remaining,
            ),
        )
        print(stable_json(service.shadow_adaptive_decision(request)))
        return 0

    if args.run_fixture:
        require_files(args.request, args.registry)
        plan = run_fixture(
            request_path=args.request,
            registry_path=args.registry,
            decision_log_path=args.decision_log if args.write_evidence else None,
        )
        print(stable_json(plan))
        return 0

    if args.run_acceptance:
        require_files(args.regression_manifest)
        report = run_acceptance(
            root=Path("."),
            regression_manifest_path=args.regression_manifest,
            decision_log_path=args.decision_log if args.write_evidence else None,
            acceptance_report_path=args.acceptance_report if args.write_evidence else None,
        )
        print(stable_json(report))
        return 0

    parser.print_help()
    return 0
