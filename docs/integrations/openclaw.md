# OpenClaw Integration

ACCE Optimizer integrates through the native OpenClaw plugin and the canonical Python DecisionService. The plugin is an adapter; it must not fork or replace the existing ACCE graph engine.

## Decision path

OpenClaw before_model_resolve
  -> local privacy-safe task profile + bounded consensus history
  -> effective OpenClaw configured provider/model catalog (identifiers only)
  -> authenticated private DecisionService bridge
  -> validate operator-owned production registry
  -> intersect registry routes with exact configured catalog pairs
  -> hard governance and task-functionality filtering
  -> ACCE-owned weighted graph cost and A* route ranking
  -> verify selected pair against effective catalog
  -> return providerOverride/modelOverride, or leave OpenClaw unchanged

OpenClaw is the source of truth for its effective runtime configuration and model execution. Its model catalog does not choose ACCE's ranking. ACCE owns route authorization, route metadata, governance, economic/quota policy, task fit, graph search, percentage scores, and the final admissible-route choice. A model appearing in OpenClaw's catalog is not automatically authorized by ACCE.

## Preserved safety boundaries

- Compatibility is pinned to OpenClaw 2026.10.5 (>=2026.10.5 <2026.10.6).
- before_model_resolve is the pre-resolution decision hook; no session mutation or model execution is performed by the decision bridge.
- If the bridge is missing/unavailable, the request is invalid, the catalog is empty, or no route survives governance, the plugin leaves OpenClaw's configured model/fallback behavior intact.
- Cloud routes remain fail-closed unless external networking and a positive per-request ceiling are explicitly configured and trusted quota/context/budget state is fresh.
- Raw prompts, attachments, conversation history, credentials, and session identifiers are not sent to the Python bridge or written to task-pattern history.
- Runtime call telemetry is observational and minimized. It is not treated as a billing or provider-quota ledger.
- Discovery telemetry can update measured latency only for an already operator-authorized route. Discovery never promotes a model into the production registry.

## Runtime catalog contract

For each adaptive decision, the plugin sends only {providerId, modelId} pairs from the effective api.config catalog. The bridge validates the full operator registry first, then derives a request-local registry view containing only exact pairs from that catalog before the graph is constructed. This prevents a stale route from winning ACCE ranking only to be rejected after the decision. An empty catalog yields no adaptive override.

The plugin also reads configured model context and price metadata locally, without credentials. OpenClaw documents model prices as USD per million tokens. However, the pre-resolution hook does not expose a complete effective session-context token count, so the current bridge does not claim an exact live per-request cost from a partial prompt estimate. Registry economic estimates remain governed inputs; unknown costs must not be treated as known free usage. Configured catalog membership is not proof of live provider availability or quota.

## Similarity consensus and learning

Task categories are derived locally (coding, research, analysis, general) and only normalized categories/timestamps are persisted. History is bounded and stored with private directory/file permissions. ACCE checks odd windows 5, 7, 9, ... and requires ceil(window_size * threshold) matches (default 80%: 4/5, 6/7, 8/9). The first window meeting the threshold establishes eligibility for a default pattern; otherwise the request receives an individual decision. The broad general category never establishes a reusable default. Consensus only governs pattern eligibility and cannot bypass per-request privacy, authorization, availability, context, quota, budget, or capability checks.

The current signature is a deterministic category heuristic, not semantic embeddings. Outcome-linked user preference learning and reusable graph-template application remain incomplete because there is not yet a safe, attributable explicit feedback channel connected to the decision flow. The implementation must not infer a user's preference or success from model-call completion alone.

## Runtime telemetry

The adapter observes OpenClaw's supported model_call_started, model_call_ended, and llm_output hooks. Only bounded provider/model identifiers, duration/outcome, request hash where supplied by OpenClaw, and aggregate token counts are retained in logs. The bridge accepts latency evidence for matching pre-authorized routes only. These hooks do not establish provider quota or authoritative billing totals.

## Remaining integration and validation work

1. Connect model availability and usage/quota status only through a supported, authorized OpenClaw 2026.10.5 interface; do not assume arbitrary in-process RPC access.
2. Connect a privacy-safe, attributable outcome/explicit-preference channel and implement reusable graph-template behavior without bypassing per-request governance.
3. Add live per-request cost estimation only when trustworthy token estimates and configured per-million-token prices are available; otherwise expose uncertainty rather than zero cost.
4. Complete isolated Gateway smoke tests for bridge reachability, hook payloads, exact catalog filtering, UI activation, route selection, data/settings preservation, fail-open behavior, and rollback.

Do not merge, publish, tag, or deploy to Aurora until code tests and the isolated/live OpenClaw 2026.10.5 smoke test pass.
