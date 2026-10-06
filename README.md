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

ACCE uses the standard Python pyproject.toml package layout and exposes the acce command-line entry point.

From a checkout:

```bash
python3 -m pip install -e .
```

Verify the installation:

```bash
acce --self-check
acce --runtime-contract
```

The package requires Python 3.10 or newer. The deterministic test suite does not require external provider connectivity.

## Development validation

The repository's CI matrix validates the package across Python 3.10, 3.11, 3.12, and 3.13.

Run locally:

```bash
python3 -m pip install -e .
python3 -m pytest -q tests
```

The clean baseline is intentionally small so the next development work can focus on the OpenClaw integration, trusted quota/budget observation, adaptive evidence collection, and production activation criteria without carrying obsolete implementation surfaces.

## Repository hygiene

This repository is the clean ACCE baseline. Obsolete historical implementation surfaces are intentionally excluded from the active codebase.

The current codebase contains no legacy routing-gate, production-pilot, canary, obsolete catalog, or provider-specific fallback architecture.