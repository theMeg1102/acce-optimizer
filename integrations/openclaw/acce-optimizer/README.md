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
