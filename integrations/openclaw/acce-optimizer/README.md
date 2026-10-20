# ACCE Optimizer OpenClaw Integration

Native OpenClaw adapter for ACCE Optimizer. Version 0.1.3 is being adapted and validated against **OpenClaw 2026.10.5**. This candidate declares compatibility with that exact host version only (`>=2026.10.5 <2026.10.6`) until later versions are independently tested. It remains **shadow-only**: it never overrides the selected provider or model.

## Discovery behavior

- On the first plugin startup, an enabled plugin automatically discovers the configured Ollama catalog when the private inventory is empty.
- Initial discovery runs as a background plugin service. Connection or catalog errors are logged and do not block Gateway startup; the next Gateway startup or a manual refresh can retry.
- If an inventory already exists, startup discovery skips it. Restarting OpenClaw does not automatically recalibrate existing records.
- Set `autoDiscoverOnStartup: false` to disable the first-run behavior.
- The `ACCE Optimizer` Control UI tab provides a **Recalibrate discovery now** button. It refreshes the configured Ollama catalog and retries telemetry that is still pending.
- Because this is a user-installed native UI plugin, enable **Settings → Labs → Custom plugin UI** in OpenClaw. That experimental setting is off by default. The first-run service and CLI still work when custom UI is disabled.
- The CLI remains available for explicit operator-controlled refreshes.

## Configuration

Configure these fields in OpenClaw → Settings → Plugins → ACCE Optimizer:

| Field | Default | Purpose |
| --- | --- | --- |
| `enabled` | `true` | Enable the plugin |
| `mode` | `shadow` | Non-mutating mode; no production routing |
| `autoDiscoverOnStartup` | `true` | Run initial discovery only when inventory is empty |
| `ollamaUrl` | `http://127.0.0.1:11434` | Explicit Ollama base URL reachable from the Gateway process |
| `inventoryPath` | `~/.openclaw/acce-optimizer-data/inventory.json` | Private durable inventory path |

For Docker deployments where Ollama runs on the host, configure a URL reachable from the container, for example `http://host.docker.internal:11434`. The plugin does not scan the network or guess alternative endpoints. An unavailable endpoint leaves the inventory unchanged and is reported in Gateway logs.

The inventory is written atomically with file permissions `0600` and parent directory permissions `0700`. Invalid or oversized inventory files are rejected rather than silently reset.

## Manual refresh

```bash
openclaw acce-optimizer discovery-refresh \
  --ollama-url http://127.0.0.1:11434 \
  --store ~/.openclaw/acce-optimizer-data/inventory.json
```

The command reports discovered, added, refreshed, telemetry-captured, and telemetry-pending counts. Repeated refreshes merge into existing records instead of duplicating model keys.

## Discovery and telemetry boundaries

- The Ollama reader queries only the explicitly configured `/api/tags` and `/api/show` endpoints, with bounded timeouts and response validation.
- Telemetry is collected only where the model's reported capabilities support the configured probe. Cloud models are left pending.
- Telemetry stores measurement evidence and aggregate timings, not generated response text.
- The coordinator preserves captured evidence, continues when an individual telemetry probe fails, and persists only after the catalog has completed successfully.
- Every inventory record has `productionEligible: false`; the refresh result always reports `productionEligible: 0`.
- The discovery feature does not connect to ACCE's authoritative production routing decision path and does not change OpenClaw's selected model.

## OpenClaw compatibility and permissions

Version 0.1.3 is a compatibility candidate, not a stable release. Its package version is aligned across package.json and openclaw.plugin.json; the OpenClaw compatibility window remains limited to the tested 2026.10.5 patch.\n\nThe development branch pins the SDK, authoring CLI, build metadata, peer dependency, and `pluginApi` compatibility range to OpenClaw 2026.10.5. The range is deliberately exact to this patch (`>=2026.10.5 <2026.10.6`); do not widen it without CI validation and a live smoke test on the intended host. OpenClaw plugin APIs are experimental. Passing build and unit tests does not replace checking discovery, registration, UI activation, and data/settings migration on a 2026.10.5 Gateway.

For non-bundled installations, the host must explicitly grant conversation-hook access:

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

The dashboard refresh surface requires the authenticated operator's `operator.admin` scope. It exposes counts and status only, not the inventory contents.

## Validation

The CI pipeline runs the plugin tests, TypeScript build, and Plugin Inspector validation against the pinned OpenClaw 2026.10.5 SDK/CLI. Tests cover catalog normalization, telemetry handling, durable private persistence, repeated discovery, first-run policy, and the compatibility metadata. Live deployment verification is still required before release, including plugin discovery/loading, native UI activation, and preservation of existing data/settings.


## Safe withdrawal and upgrade validation

For the Aurora OpenClaw 2026.10.5 migration, do not copy generated files directly into the active extension directory and do not use `openclaw plugins install acce-optimizer --force` as the first repair step.

1. Record the current plugin registry/inspection output, config entry, and a checksum plus private backup of the inventory before changing active state.
2. Use the supported reversible command `openclaw plugins disable acce-optimizer`. This changes enablement without removing the installed package or its configuration fields. Confirm the effective status and check whether compatibility warnings continue; disabling may not suppress cold-discovery diagnostics for an incompatible package.
3. Rebuild and validate this branch against the pinned OpenClaw 2026.10.5 CLI. The build uses an isolated temporary OpenClaw state directory and checks that `dist/index.js`, generated manifest metadata, and native Control UI assets exist.
4. Validate the packed artifact before installation. The official OpenClaw plugin installer should be used in the isolated test environment so its install registry/metadata is created through the supported lifecycle. Do not reactivate the live plugin until this test passes.
5. Compare plugin settings and inventory before and after the test. The host-compatibility change does not intentionally change the inventory record schema. Never delete or regenerate the existing inventory to work around a migration warning.

The plugin settings live in the OpenClaw config entry for `plugins.entries.acce-optimizer`; the model inventory is separate at the configured `inventoryPath` (default `~/.openclaw/acce-optimizer-data/inventory.json`). Keep both, along with Doctor captures and backups. Do not run `openclaw update repair`, `openclaw doctor --fix`, or a forced reinstall until the exact migration owner and affected state have been identified.

The development branch intentionally does not claim the installation is repaired merely because CI passes. Before release, the isolated OpenClaw 2026.10.5 environment must confirm clean discovery, successful runtime registration, working Control UI refresh, no repeated plugin diagnostics, and unchanged inventory/settings. Then deploy the same validated artifact and retain a documented rollback copy.
