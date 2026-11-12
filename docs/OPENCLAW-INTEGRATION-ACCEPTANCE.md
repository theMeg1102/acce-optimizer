# ACCE ↔ OpenClaw 2026.10.5: integration acceptance gate

This document is an **acceptance checklist**, not a claim that the integration is complete.
A green CI build alone does not authorize a release, merge, or Aurora deployment.

## Required functional scope

| Capability | Implementation evidence | Release acceptance |
| --- | --- | --- |
| OpenClaw native plugin registration and provenance | SDK contract, build/manifest, Plugin Inspector | Inspect a **running isolated Gateway**: plugin loaded, trusted provenance, registered hooks/services/UI; no `provenance-invalid` or empty hook registration |
| OpenClaw as model source of truth | Effective configured catalog + read-only CLI runtime status | Verify exact provider/model intersection, real availability and rejection of stale, ambiguous, or absent status |
| ACCE owns route selection | Python `DecisionService.adaptive_decision()` | End-to-end authorized decision through bridge and native `before_model_resolve` with real Gateway request |
| Functional/economic optimization | Registry-governed graph, quality, cost, latency, context, privacy, availability, reliability, quota constraints | Demonstrate admissible ranking and A*/Dijkstra graph decisions on deterministic multi-route fixtures; verify local-first and cloud advantage thresholds (30% normal, 10% urgent) against agreed policy |
| No hardcoded production providers | Operator-maintained production registry and discovered inventory kept separate | Discovery must not create or authorize production routes; incomplete/example registry must fail closed |
| Cloud governance | External network disabled by default, per-request cost cap, trusted runtime quota/context and usage ledger | Prove missing/stale/invalid quota or ledger never admits cloud; do not infer quota from OpenClaw usage counters |
| User/operator routing preferences | Configured preferences and current-turn explicit requests | Validate Auto/Ask/Learned semantics and precedence, exact-match user choice, and hard-governance enforcement; **do not claim full coverage until demonstrated** |
| Task-pattern learning | Private category-only history, 80% odd-window consensus, successful route-order reuse | Verify 4/5, 6/7 etc., bounded private persistence, no prompt/session storage, and safe non-consensus fallback; separately verify any 85% learning criterion in the agreed design |
| Telemetry and reliability | Native typed hooks, minimized observations and authorized outcome ledger | Verify actual Gateway hook emission, attribution, bounded updates and no raw prompt/credentials in stored or transmitted data |
| Ollama discovery and calibration | Read-only catalog, bounded probes, atomic private inventory | Verify startup/manual/UI refresh, failed-probe preservation, no automatic route promotion |
| Failure and rollback | Shadow mode, explicit override opt-in, default-model fallback | Exercise bridge unavailable, unauthorized override, CLI failure, service restart, plugin disable and recovery; verify config and inventory checksums unchanged |
| Network security | Loopback HTTP only, HTTPS for remote bridge, bearer token | Verify unreachable bridge, bad token, remote HTTP rejection, and private endpoint handling |
| Packaging and compatibility | Pinned OpenClaw 2026.10.5, build, Inspector, package verification | Validate actual installed candidate in a clean, isolated Gateway; confirm version and plugin UI |
| Dependency security | Production-only npm audit | Zero production advisories at audit time; triage development advisories before release |

## Mandatory acceptance sequence

1. Keep the PR in draft and leave Aurora production untouched.
2. Run TypeScript/Vitest, Python matrix, build, Plugin Inspector, package verification, and production dependency audit.
3. Launch an **isolated OpenClaw 2026.10.5 Gateway** with disposable HOME, config, credentials, data, and ports; no shared Aurora bind mounts.
4. Inspect plugin registration/provenance, hook names, services and UI; record evidence.
5. Connect an isolated authenticated Python decision bridge and an operator-authorized deterministic registry. Test available local route, governed cloud exclusion, explicit authorized override, and default fallback.
6. Exercise learning, observation, failed refresh, bridge outage, plugin disable, restart, and rollback; compare pre/post config and data checksums.
7. Review every row above with evidence; any unimplemented or untested feature remains an explicit blocker rather than silently reducing scope.
8. Only after all gates pass, separately request authorization for any Aurora production change.

## Current evidence and gaps (2026-11-12)

- Verified: CI run 43332904156 succeeded for commit d812619; earlier unit/integration, real OpenClaw CLI catalog smoke, plugin Inspector, build, packaging, and Python tests have passed.
- Verified: isolated uncredentialed OpenClaw CLI catalog is fail-closed against ACCE runtime override policy.
- **Not verified:** running isolated Gateway plugin activation/provenance, actual model-resolution hook invocation, end-to-end bridge-to-Gateway override, UI activation, rollback, and Aurora-specific networking.
- **Scope requiring explicit reconciliation:** Auto/Ask/Learned modes, the separately discussed 85% learning threshold, full graph-topology caching, cross-turn user preference learning, and current-turn explicit route preference behavior. Do not treat documentation statements or a soft learned-route template as evidence these are fully implemented.
- Development dependency alerts remain for a later, pre-release triage phase; production audit reports zero at this checkpoint.
