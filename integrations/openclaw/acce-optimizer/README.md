# ACCE Optimizer OpenClaw Integration

Native OpenClaw adapter for ACCE Optimizer. Version 0.1.2 targets OpenClaw 2026.9.8 and remains **shadow-only**: it never overrides the selected provider or model.

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

The plugin is built and tested against OpenClaw 2026.9.8. Plugin APIs are experimental, so the compatibility range is pinned to the tested minor release.

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

The CI pipeline runs the plugin tests, TypeScript build, and Plugin Inspector validation. Tests cover catalog normalization, telemetry handling, durable private persistence, repeated discovery, and the first-run policy. Live deployment verification is still required for each OpenClaw environment before release.
