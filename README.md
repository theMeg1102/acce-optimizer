# ACCE Optimizer OpenClaw Integration

Native OpenClaw adapter for ACCE Optimizer. This integration branch targets **OpenClaw 2026.10.5** (`>=2026.10.5 <2026.10.6`). In `adaptive` mode, the plugin delegates selection to the existing Python `DecisionService.adaptive_decision()` graph engine and returns its governed `providerOverride` / `modelOverride` through the supported `before_model_resolve` hook. `shadow` mode remains available for non-mutating observation.

## Discovery behavior

- On the first plugin startup, an enabled plugin automatically discovers the configured Ollama catalog when the private inventory is empty.
- Initial discovery runs as a background plugin service. Connection or catalog errors are logged and do not block Gateway startup; the next Gateway startup or a manual refresh can retry.
- If an inventory already exists, startup discovery skips it. Restarting OpenClaw does not automatically recalibrate existing records.
- Set `autoDiscoverOnStartup: false` to disable the first-run behavior.
- The `ACCE Optimizer` Control UI tab provides a **Recalibrate discovery now** button. It refreshes the configured Ollama catalog and remeasures discovered models so new latency evidence can update existing graph routes. A failed re-probe preserves the last successful measurement.
- Because this is a user-installed native UI plugin, enable **Settings → Labs → Custom plugin UI** in OpenClaw. That experimental setting is off by default. The first-run service and CLI still work when custom UI is disabled.
- The CLI remains available for explicit operator-controlled refreshes.


### Runtime status polling

ACCE refreshes OpenClaw's published model availability and normalized provider usage windows in the background using the documented read-only CLI commands `openclaw models list --all --json` and `openclaw status --usage --json`. The default interval is 300 seconds (configurable from 60 to 900). The model-resolution hook never launches CLI processes. The bridge requires a fresh model snapshot, admits only exact provider/model rows whose `available` value is `true`, and excludes quota-metered cloud routes when provider usage is stale, missing, or exhausted. If the CLI is unavailable or the model snapshot is stale, ACCE does not override OpenClaw's model choice.

### Explicit route preferences

An operator may configure preferredRoutes by task class in plugin config, for example:

```json
{
  "preferredRoutes": {
    "coding": { "providerId": "local-provider", "modelId": "example-local-model" }
  }
}
```

The bridge accepts a preference only when the exact provider/model pair exists in both OpenClaw's effective configured catalog and the operator-authorized ACCE registry. ACCE applies a soft penalty to other admissible routes; it never overrides hard governance. OpenClaw separately requires plugins.entries.acce-optimizer.llm.allowModelOverride: true and, if configured, a matching llm.allowedModels entry before the plugin can return a model override.

## Configuration

Configure these fields in OpenClaw → Settings → Plugins → ACCE Optimizer:

| Field | Default | Purpose |
| --- | --- | --- |
| `enabled` | `true` | Enable the plugin |
| `mode` | `adaptive` | `adaptive` applies the governed A* graph decision; `shadow` observes only |
| `decisionServiceUrl` | unset | Private Python ACCE DecisionService bridge URL; HTTP is allowed only on loopback, and remote endpoints must use HTTPS |
| `decisionServiceToken` | unset | Secret bearer token for the bridge. Never send it over remote plain HTTP |
| `allowExternalNetwork` | `false` | Explicitly allow cloud routes, subject to fresh trusted state and route governance |
| `maxCloudCostUsd` | `0` | Per-request cloud cost ceiling; cloud routes stay blocked at zero |
| `autoDiscoverOnStartup` | `true` | Run initial discovery only when inventory is empty |
| `ollamaUrl` | `http://127.0.0.1:11434` | Explicit Ollama base URL reachable from the Gateway process |
| `inventoryPath` | `~/.openclaw/acce-optimizer-data/inventory.json` | Private durable inventory path |
| `similarityHistoryPath` | `~/.openclaw/acce-optimizer-data/task-history.json` | Private history of normalized task categories; no raw prompts |
| `similarityThreshold` | `0.8` | Minimum fraction of similar observations needed to establish a default task pattern |

For Docker deployments where Ollama runs on the host, configure a URL reachable from the container, for example `http://host.docker.internal:11434`. The plugin does not scan the network or guess alternative endpoints. An unavailable endpoint leaves the inventory unchanged and is reported in Gateway logs.

The inventory is written atomically with file permissions `0600` and parent directory permissions `0700`. Invalid or oversized inventory files are rejected rather than silently reset.

## Connect the existing Python decision engine

The OpenClaw plugin is Node.js and the canonical graph engine is Python. They are connected by a small standard-library HTTP bridge; the plugin does not reimplement or fork the graph algorithm.

Install the repository's Python package in the ACCE runtime environment, then start the bridge against the operator-maintained registry:

    export ACCE_REGISTRY_PATH=/absolute/path/to/registry.json
    export ACCE_DECISION_BIND=127.0.0.1
    export ACCE_DECISION_PORT=18791
    acce-decision-server

If the Gateway runs in Docker and the bridge runs on the Aurora host, bind only to a private host interface reachable from that container, set a strong ACCE_DECISION_TOKEN, and firewall port 18791 to the Docker network. The Python bridge uses plain HTTP and does not terminate TLS itself, so expose it to the Gateway through a trusted HTTPS reverse proxy or TLS tunnel; the plugin rejects non-loopback HTTP URLs to protect bearer tokens. Configure decisionServiceUrl with the HTTPS address reachable from the container and decisionServiceToken with the same token. A loopback URL inside the Gateway container points to the container itself, not the host.

The bridge exposes GET /health and POST /v1/decide, /v1/observations, and /v1/outcomes. It reads the operator-owned registry for every decision, requires the strict production-registry contract, and calls DecisionService.adaptive_decision(). An example or incomplete registry is rejected rather than activated. Minimized latency/context evidence is stored separately at ACCE_OBSERVATIONS_PATH (default: acce-discovery-observations.json beside the registry); route outcomes are stored at ACCE_ROUTE_OUTCOMES_PATH (default: acce-route-outcomes.json beside the registry). Both stores use atomic writes and private file permissions. Effective context budgets only reduce a route's admitted context window. Configured `maxTokens` is a hard output cap when a request supplies an expected-output token estimate; ACCE excludes routes that cannot meet that requirement rather than silently clipping the task. New inventory entries are never promoted to production routes. Set ACCE_DECISION_LOG_PATH to persist minimized decision evidence for later analysis; the existing logger hashes the task summary and does not store raw prompt text.

Cloud routes are fail-closed by default. They require `allowExternalNetwork: true`, a positive `maxCloudCostUsd`, and fresh trusted quota/context state on the bridge. Configure `ACCE_TRUSTED_STATE_TELEMETRY_PATH` and `ACCE_USAGE_LEDGER_PATH` to existing, authorized state files; optionally set `ACCE_MONTHLY_CLOUD_BUDGET_USD` and `ACCE_BUDGET_PERIOD`. The bridge validates telemetry freshness using the existing `TrustedRuntimeState` contract. If either file is absent, stale, or invalid, the request is clamped to local-only with a zero cloud-cost ceiling. Do not fabricate these files or infer quota from model discovery.

For a safe rollback, set mode to shadow or remove decisionServiceUrl. When the bridge is not configured or is unavailable, the plugin fails open to OpenClaw's configured model.

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
- Every inventory record remains `productionEligible: false`; discovery alone never authorizes a new route.
- Captured `latencyMs` and effective `contextTokenBudget` telemetry are sent to the decision bridge as minimized evidence. The bridge merges bounded per-model observations, updates latency estimates and applies a conservative context-window cap only for already operator-configured registry routes whose provider/model identifiers match; it never auto-adds a route or invents quality, privacy, cost, or quota metadata. Route outcomes are separately validated against exact authorized route/provider/model triples and only affect task-signature-specific reliability after five observations.
- Adaptive selection uses the existing Python graph search and route-governance checks. If the bridge is unavailable, the request is invalid, or no admissible adaptive route exists, the hook leaves OpenClaw's configured model unchanged. No prompt, attachments, history, or session identifier is sent to the bridge.

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


## OpenClaw-native runtime observation and task-pattern consensus

The adapter reads the effective in-memory configuration exposed as `api.config` by the pinned OpenClaw 2026.10.5 plugin SDK. It extracts provider/model identifiers and configured metadata (input modalities, context window, and cost fields when present); it never copies provider credentials. For every adaptive decision, the plugin sends exact provider/model identifiers plus allowlisted context and pricing metadata to the Python bridge; it never copies credentials. After validating the operator-owned production registry, ACCE intersects its candidate routes with those exact configured pairs before graph construction and ranking. OpenClaw supplies current configuration facts, while ACCE retains route authorization, governance, functional filtering, graph costs, and ranking authority. An empty/unreadable catalog yields no adaptive candidate and leaves OpenClaw's configured model/fallback behavior intact.

The integration observes the official `model_call_started`, `model_call_ended`, and `llm_output` hooks. It emits minimized aggregate provider/model, duration, outcome, token-usage, and effective context-budget fields only. Measured call duration and effective context budgets update matching operator-approved routes conservatively. Route outcomes are authenticated against a one-time issued-decision receipt, then update task-scoped reliability only after five observations. When 80% consensus is eligible, the most recent successful route-order template can influence ranking softly; the graph and all hard constraints are rebuilt for each request. Usage telemetry is observational and is not a trusted quota or billing ledger; ACCE does not infer provider quota, exact cloud cost, quality, or production eligibility from a call event.

Task-pattern reuse is governed separately from model ranking. ACCE stores normalized task-category signatures only, never raw prompt text, in a private bounded history file (0600 file, 0700 directory). It evaluates odd sample windows of 5, 7, 9, and onward. A historical pattern is eligible as a default only if at least 80% of the observations in a window match the current normalized category signature; required matches are rounded up (4/5, 6/7, 8/9). It uses the smallest window that passes. If no available odd window passes, ACCE records that no default pattern is established and continues with an individual decision; it does not claim historical consensus. This consensus percentage is not a model ranking score.

The plugin correlates OpenClaw's explicit agent_end success/failure with the exact task observation using a transient in-memory runId and an opaque observation ID; run/session IDs are not persisted. The selected decision ID, exact authorized route, and bounded route ranking are stored on that observation. Outcomes are sent to a separate bounded bridge ledger, validated against the operator-authorized registry, and used as task-signature-specific reliability estimates only after five observations, shrunk toward the registry prior. When the 80% odd-window consensus is eligible, ACCE may reuse the most recent successful route-order template as a soft ranking penalty; it rebuilds the graph and reapplies all hard checks for each request. This is not yet full graph-topology caching or per-user preference learning. Explicit operator preferences are configurable by task class; user identity is not persisted, and run success is not treated as explicit user preference.

For the native API contract, see the official [OpenClaw 2026.10.5 Plugin SDK overview](https://docs.openclaw.ai/plugins/sdk-overview), [typed hook reference](https://docs.openclaw.ai/plugins/hooks/reference), and [Gateway models and usage RPC reference](https://docs.openclaw.ai/gateway/protocol/rpc-system-and-channels). OpenClaw documents api.runtime.gateway.request for bundled/trusted official plugins and rejects arbitrary external plugins. Live models.list availability and usage.status quota refresh therefore remain blocked until a supported read-only capability or explicitly trusted installation path is available; ACCE will not bypass this trust boundary with private WebSocket/RPC calls. These APIs are experimental and the integration remains pinned to 2026.10.5.

## Validation

The CI pipeline runs the plugin tests, TypeScript build, and Plugin Inspector validation against the pinned OpenClaw 2026.10.5 SDK/CLI. The Python tests cover the decision bridge and telemetry-to-route integration; the plugin tests cover bridge requests, fail-open behavior, and evidence sync. Live deployment verification is still required before release, including service reachability from the Gateway container, plugin discovery/loading, native UI activation, route selection against the actual registry, and preservation of existing data/settings.


## Safe withdrawal and upgrade validation

For the Aurora OpenClaw 2026.10.5 migration, do not copy generated files directly into the active extension directory and do not use `openclaw plugins install acce-optimizer --force` as the first repair step.

1. Record the current plugin registry/inspection output, config entry, and a checksum plus private backup of the inventory before changing active state.
2. Use the supported reversible command `openclaw plugins disable acce-optimizer`. This changes enablement without removing the installed package or its configuration fields. Confirm the effective status and check whether compatibility warnings continue; disabling may not suppress cold-discovery diagnostics for an incompatible package.
3. Rebuild and validate this branch against the pinned OpenClaw 2026.10.5 CLI. The build uses an isolated temporary OpenClaw state directory and checks that `dist/index.js`, generated manifest metadata, and native Control UI assets exist.
4. Validate the packed artifact before installation. The official OpenClaw plugin installer should be used in the isolated test environment so its install registry/metadata is created through the supported lifecycle. Do not reactivate the live plugin until this test passes.
5. Compare plugin settings and inventory before and after the test. The host-compatibility change does not intentionally change the inventory record schema. Never delete or regenerate the existing inventory to work around a migration warning.

The plugin settings live in the OpenClaw config entry for `plugins.entries.acce-optimizer`; the model inventory is separate at the configured `inventoryPath` (default `~/.openclaw/acce-optimizer-data/inventory.json`). Keep both, along with Doctor captures and backups. Do not run `openclaw update repair`, `openclaw doctor --fix`, or a forced reinstall until the exact migration owner and affected state have been identified.

The development branch intentionally does not claim the installation is repaired merely because CI passes. Before release, the isolated OpenClaw 2026.10.5 environment must confirm clean discovery, successful runtime registration, working Control UI refresh, no repeated plugin diagnostics, and unchanged inventory/settings. Then deploy the same validated artifact and retain a documented rollback copy.
