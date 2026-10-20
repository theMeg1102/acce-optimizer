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
