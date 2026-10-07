# Adaptive Context and Cost Engine (ACCE)

ACCE is a governed adaptive optimization engine for model routing, cost and quota optimization, context-aware execution planning, quality, latency, and user preferences.

## Current status

ACCE is an active pre-1.0 development project with a validated clean baseline.

The current implementation provides:

- deterministic weighted execution graphs;
- Dijkstra as the deterministic shortest-path baseline;
- A* search with an admissible heuristic;
- immutable graph and resource-state snapshots;
- hard governance before optimization;
- quota and budget scarcity as independent routing signals;
- configurable local-first preferences and cloud escalation thresholds;
- evidence-backed route learning and similarity-gated preference promotion;
- a stable DecisionService.decide(request) contract;
- read-only adaptive evaluation against the authoritative decision; and
- read-only OpenClaw observation boundaries.

The authoritative execution decision remains separate from adaptive optimization while the adaptive planner is validated. **Adaptive routing is not yet applied to production execution.**

## Runtime contract

The current runtime contract is intentionally conservative:

- **Production adaptive routing:** disabled.
- **Adaptive shadow evaluation:** enabled and read-only.
- **Model execution by ACCE:** not requested.
- **Conversation content recording by adaptive evaluation:** disabled.
- **OpenClaw session mutation:** disabled.
- **Quota inference:** disabled.
- **Subscription quota conversion to USD:** disabled.
- **Graph mutation during a decision:** disabled.
- **Learning direct route selection:** disabled; learning updates future weights and preferences only.
- **Production registry validation:** enabled.
- **Production registry activation:** disabled until activation evidence is sufficient.

The public compatibility surface is `DecisionService.decide(request)`.

The contract identifier and version are exposed by `runtime_contract()` and `DecisionService`.

## Routing policy

The default policy is configurable per installation and currently establishes:

- minimum quality threshold: `0.75`;
- strong local preference factor: `0.80`;
- normal cloud quality-advantage threshold: `30%`;
- urgent cloud quality-advantage threshold: `10%`;
- learned-preference promotion after `5` observations;
- learned-preference agreement threshold: `85%`;
- demand similarity threshold: `80%`;
- task similarity threshold: `80%`;
- preference observations must remain an odd count.

Quota and budget state are supplied as trusted observations. ACCE does not invent provider quota values or convert subscription quota into monetary cost.

## Architecture

ACCE is vendor-neutral.

- **ACCE** owns governance, graph construction, optimization, evidence evaluation, and routing policy.
- **Models and providers** are represented as candidate graph routes.
- **Dijkstra and A*** optimize the governed graph.
- **Learning** updates future route weights and user-preference evidence; it does not directly choose a route.
- **OpenClaw** is an observation and execution boundary, not the routing authority.
- **Execution** remains outside ACCE.

The initial integration path is deliberately read-only so routing behavior can be validated before production activation.

## Installation

ACCE uses the standard Python `pyproject.toml` package layout and exposes the `acce` command-line entry point.

### Recommended: isolated virtual environment

For a checkout on a host where Python package installation is managed by the operating system, create an isolated virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

This is the recommended installation path because it keeps ACCE dependencies isolated from the host Python environment.

### Alternative: direct installation

If the host permits package installation into the active Python environment:

```bash
python3 -m pip install -e .
```

Some Linux distributions mark their system Python installation as externally managed. In that case, `pip` may reject direct installation outside a virtual environment. This is a host packaging policy, not an ACCE requirement; use the virtual-environment procedure above instead.

Verify the installation:

```bash
acce --self-check
acce --runtime-contract
```

## First decision

The repository includes a vendor-neutral, non-production request and registry example so a new user can execute the core decision flow immediately after installation.

Run:

```bash
acce --run-decision \
  --request examples/request.json \
  --registry examples/registry.json
```

The example contains one local model route and produces an offline execution plan. ACCE does not execute the model or any external action.

The same example can be used for adaptive shadow evaluation:

```bash
acce --run-adaptive-shadow \
  --request examples/request.json \
  --registry examples/registry.json
```

See [Input Contract](docs/input-contract.md) for the request and registry structure and for the distinction between normal and production registries.

## Command-line decision evaluation

ACCE keeps decision inputs explicit and installation-specific. A decision request and registry are supplied by the host; ACCE does not embed a machine-specific model inventory.

Run one authoritative deterministic decision:

```bash
acce --run-decision --request PATH --registry PATH
```

Run adaptive evaluation without changing the authoritative decision:

```bash
acce --run-adaptive-shadow --request PATH --registry PATH
```

Validate a production registry:

```bash
acce --validate-production-registry --registry PATH
```

Replace `PATH` with an actual file path. The literal string `PATH` is documentation notation, not a file.

The CLI intentionally keeps `--request` and `--registry` optional at argument-parsing time because they are conditional inputs: they are required only by commands that consume them. ACCE validates those dependencies at runtime and reports the missing option explicitly. This keeps command-specific requirements explicit without making unrelated commands depend on decision inputs.

The package requires Python 3.10 or newer. The deterministic test suite does not require external provider connectivity.

## Production registry

Production registry validation is intentionally stricter than the normal decision registry.

A production registry must represent trusted, measured inventory and satisfy the complete production contract. Placeholder values are not accepted, and production validation does not itself enable production routing.

Do not use `examples/registry.json` as a production inventory. It is deliberately a minimal local example for offline evaluation.

See [Input Contract](docs/input-contract.md) for the production validation requirements.

## Development validation

The repository's CI matrix validates the package across Python 3.10, 3.11, 3.12, and 3.13.

Run locally:

```bash
python3 -m pip install -e .
python3 -m pytest -q tests
```

The baseline is intentionally small so the next development work can focus on the OpenClaw integration, trusted quota/budget observation, adaptive evidence collection, and production activation criteria.

### Preference learning defaults

Preference learning starts at 5 observations and evaluates only odd checkpoints, increasing incrementally to 7, 9, 11, and so on while the promotion criteria are not met. Defaults are 85% agreement, 85% confidence, 80% demand similarity, 80% task similarity, and `preference_mode = "learned"`; all are configurable. An effective change in the preferred route resets the learning cycle to 5 observations. Confirming the existing preference does not reset evidence.
