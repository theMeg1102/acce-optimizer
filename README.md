# Adaptive Context and Cost Engine (ACCE)

ACCE is a governed adaptive optimization engine for model routing, cost and quota optimization, context-aware execution planning, quality, latency, and user preferences.

## Current status

ACCE is an active pre-1.0 development project. The current implementation provides a deterministic weighted execution graph, Dijkstra and A* search, immutable resource state, evidence-backed learning, configurable user preferences, governance-before-search, and a read-only adaptive evaluation path.

The authoritative execution decision remains separate from adaptive optimization while the adaptive planner is validated. Adaptive routing is not yet applied to production execution.

## Design principles

- Vendor-neutral model and provider routing.
- Hard governance constraints are evaluated before optimization.
- Dijkstra provides the deterministic shortest-path baseline.
- A* provides optimized search with an admissible heuristic.
- Quota and budget scarcity are independent resource signals.
- Local execution receives a strong preference when it satisfies the minimum quality threshold.
- Cloud escalation requires a configurable material quality advantage.
- Learning updates future graph weights and preferences; it does not directly select a route.
- Every routing decision is based on an immutable graph and resource-state snapshot.
- Execution remains outside ACCE; integrations provide observation and execution boundaries.

## Repository

The repository is intentionally built as a clean ACCE baseline. Historical implementation artifacts and obsolete integration surfaces are not part of the current codebase.

## Development

The initial clean baseline is under active validation.


Python 3.10+ is required. The project is designed so the deterministic test suite can run without external provider connectivity.
