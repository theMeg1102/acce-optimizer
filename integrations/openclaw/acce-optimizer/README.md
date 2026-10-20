# ACCE Optimizer OpenClaw Integration

This directory contains the OpenClaw-native adapter for ACCE Optimizer.

## Current phase

The adapter is intentionally limited to **shadow mode**.

- The hook is registered with OpenClaw's typed `before_model_resolve` API.
- The plugin is enabled by default in shadow mode.
- Shadow observations do not return `providerOverride` or `modelOverride`.
- The ACCE core remains independent of OpenClaw.
- Production routing is not enabled by this integration.

## OpenClaw compatibility

The adapter is built and tested against OpenClaw 2026.9.8. OpenClaw plugin APIs are experimental, so the compatibility range is pinned to the tested minor release.

## Required host permission

When this plugin is enabled as a non-bundled OpenClaw plugin, the host configuration must explicitly grant conversation-hook access:

```json
{
  "plugins": {
    "entries": {
      "acce-optimizer": {
        "enabled": true,
        "hooks": {
          "allowConversationAccess": true
        }
      }
    }
  }
}
```

This permission is controlled by OpenClaw and is separate from ACCE's own routing and governance controls.

## Runtime validation

The integration is validated as a hook-only OpenClaw plugin. Validation confirms runtime registration of `before_model_resolve`, conversation-hook permission, and the absence of production model/provider overrides.

## Next integration phase

The next phase will connect the shadow hook to ACCE's public `DecisionService.decide(request)` contract through an explicit adapter boundary. The adapter must preserve ACCE's governance, quota, context, and production-routing constraints and must remain non-mutating while shadow validation is in progress.


## Governed discovery foundation

`src/discovery.ts` now provides deterministic inventory primitives for normalized model observations from OpenClaw, Ollama, configured providers, and custom providers:

- repeated discovery merges sources/capabilities and retains first-seen timestamps, captured telemetry, and explicit user-added state;
- a new model starts as `DISCOVERED`; telemetry capture advances its evidence state without enabling a route;
- adding a discovered model requires an explicit `markModelUserAdded` call;
- every inventory record hard-codes `productionEligible: false`. Production eligibility remains owned by ACCE's authoritative registry/governance path.

**Integration boundary:** these are tested domain primitives, not yet a live catalog poller or Settings button. A catalog reader must supply observations through an authorized OpenClaw interface (or a narrowly scoped read-only bridge); this plugin must not assume arbitrary Gateway methods are callable from an untrusted plugin. Telemetry collection and durable storage/UI orchestration remain follow-on integration work. No production routing is enabled.


### Refresh orchestration contract

`src/discovery-coordinator.ts` adds a caller-triggered orchestration boundary:

- `CatalogReader` is injected, so only a deployment-authorized catalog adapter can supply rows;
- `DiscoveryStore` is injected, so production wiring must choose durable, access-controlled persistence rather than the in-memory test store;
- telemetry bootstrap is injected and must return actual measurement evidence; errors or absent measurements leave the model pending;
- the coordinator preserves existing captured telemetry, continues when an individual telemetry probe fails, and saves only after all catalog readers complete successfully;
- the result always reports `productionEligible: 0`.

Tests cover refresh merging, historical evidence retention, telemetry failure, and avoiding persistence of a partial catalog refresh. This is orchestration infrastructure, not yet a live OpenClaw Gateway adapter, durable production store, or Settings control. Those pieces must be connected before claiming end-to-end autodiscovery.


### OpenClaw catalog adapter

`src/openclaw-catalog-reader.ts` maps the official `models.list` response shape into normalized discovery rows, supports `all` and `configured` views, deduplicates provider/model identities, and rejects malformed responses. The adapter accepts an `AuthorizedGatewayReader` dependency rather than making a privileged request itself. Wire it only to an authenticated Gateway client or a narrowly scoped read-only bridge. The repository now tests this mapping independently, but the live authorized transport and durable store are not yet wired into plugin runtime or Settings.


### Configured Ollama discovery and durable inventory

- `src/ollama-catalog-reader.ts` queries only an explicitly supplied Ollama base URL at `/api/tags`; it does not scan localhost or private networks. It rejects embedded credentials, uses a bounded timeout, validates the response, and normalizes model metadata.
- `src/json-file-discovery-store.ts` provides single-process durable JSON storage at an explicitly configured absolute path. Writes use a same-directory temporary file and atomic rename with private file permissions; malformed, oversized, or production-eligible records are rejected instead of silently resetting inventory.
- Tests cover endpoint validation, API errors, timeouts, persistence, permissions, malformed files, size limits, and the production-eligibility invariant.

These are now tested integration components. They are not yet wired into OpenClaw plugin startup, a Gateway RPC method, or a Settings button. End-to-end autodiscovery still requires that runtime wiring and a verified authorized catalog transport.


### Operator-triggered refresh command

The plugin now registers `openclaw acce-optimizer discovery-refresh`. It requires an explicit Ollama endpoint and an absolute inventory path, for example:

```bash
openclaw acce-optimizer discovery-refresh \
  --ollama-url http://localhost:11434 \
  --store ~/.openclaw/acce-discovery.json
```

The command expands a leading `~/`, queries only that configured endpoint, atomically persists the inventory, and prints counts. The output explicitly reports `productionEligible: 0`. It does not yet replace the planned Settings autodiscovery button; it provides a real operator-triggered path while the Settings UI and authorized OpenClaw catalog transport are developed.
