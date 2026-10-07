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
from acce_optimizer.core.registry import validate_production_registry
from acce_optimizer.core.runner import run_decision
from acce_optimizer.core.runtime import (
    DecisionService,
    EconomicPolicy,
    QuotaPolicy,
    runtime_contract,
)


def build_self_check() -> dict:
    return {
        "system": "adaptive-context-and-cost-engine",
        "name": "ACCE",
        "version": __version__,
        "namespace": "acce_optimizer.core",
        "compatibility_entrypoint": "acce_optimizer",
        "phase": "Adaptive Routing Validation",
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
            "--run-decision",
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
    parser.add_argument("--self-check", action="store_true", help="Validate ACCE runtime availability and core contract status.")
    parser.add_argument("--runtime-contract", action="store_true", help="Print the public runtime contract and safety constraints.")
    parser.add_argument("--run-decision", action="store_true", help="Run one deterministic decision from --request and --registry.")
    parser.add_argument("--run-acceptance", action="store_true", help="Run configured regression cases from --regression-manifest.")
    parser.add_argument("--run-adaptive-shadow", action="store_true", help="Evaluate the adaptive shadow path without changing the authoritative decision.")
    parser.add_argument("--validate-production-registry", action="store_true", help="Validate a complete production registry supplied with --registry.")
    parser.add_argument("--measure-ollama", action="store_true", help="Measure configured local model inventory with --ollama-model.")
    parser.add_argument("--observe-openclaw-status", action="store_true", help="Read OpenClaw status evidence without mutating the session.")
    parser.add_argument("--openclaw-status-input", default="-", help="JSON file containing OpenClaw status evidence, or - for stdin.")
    parser.add_argument("--openclaw-session-key", help="Session key required for safe OpenClaw observation.")
    parser.add_argument("--safe-status-output", type=Path, help="Optional path for minimized safe OpenClaw status evidence.")
    parser.add_argument("--ollama-endpoint", default="http://127.0.0.1:11434", help="Ollama endpoint used for local inventory measurement.")
    parser.add_argument("--ollama-model", action="append", default=[], help="Model identifier to measure; repeat for multiple models.")
    parser.add_argument("--measurement-output", type=Path, help="Optional path for the Ollama measurement report.")
    parser.add_argument("--request", type=Path, metavar="PATH", help="Decision request JSON input. Required by --run-decision and --run-adaptive-shadow.")
    parser.add_argument("--registry", type=Path, metavar="PATH", help="ACCE registry JSON input. Required by --run-decision, --run-adaptive-shadow, and --validate-production-registry.")
    parser.add_argument("--decision-log", type=Path, metavar="PATH", help="Optional decision log output when --write-evidence is enabled.")
    parser.add_argument("--regression-manifest", type=Path, metavar="PATH", default=None, help="Configured regression manifest required by --run-acceptance.")
    parser.add_argument("--acceptance-report", type=Path, metavar="PATH", default=None, help="Optional acceptance report output when --write-evidence is enabled.")
    parser.add_argument("--quota-remaining", type=float, default=1.0, help="Trusted remaining cloud quota fraction used by offline evaluation.")
    parser.add_argument("--monthly-budget-usd", type=float, default=20.0, help="Configured monthly cloud budget used by offline evaluation.")
    parser.add_argument("--monthly-spend-usd", type=float, default=0.0, help="Configured monthly cloud spend used by offline evaluation.")
    parser.add_argument("--write-evidence", action="store_true", help="Persist minimized decision or acceptance evidence to the requested output path.")
    args = parser.parse_args(argv)

    def require_files(*named_paths: tuple[str, Path | None]) -> None:
        missing = [
            option if path is None else f"{option}={path}"
            for option, path in named_paths
            if path is None or not path.is_file()
        ]
        if missing:
            parser.error("missing required input: " + ", ".join(missing))

    if args.self_check:
        print(stable_json(build_self_check()))
        return 0

    if args.runtime_contract:
        print(stable_json(runtime_contract()))
        return 0

    if args.validate_production_registry:
        require_files(("--registry", args.registry))
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
            require_files(("--openclaw-status-input", status_path))
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
        require_files(("--request", args.request), ("--registry", args.registry))
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

    if args.run_decision:
        require_files(("--request", args.request), ("--registry", args.registry))
        plan = run_decision(
            request_path=args.request,
            registry_path=args.registry,
            decision_log_path=args.decision_log if args.write_evidence else None,
        )
        print(stable_json(plan))
        return 0

    if args.run_acceptance:
        require_files(("--regression-manifest", args.regression_manifest))
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
