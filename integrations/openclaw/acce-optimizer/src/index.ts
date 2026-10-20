import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { defineFeaturePlugin } from "openclaw/plugin-sdk/feature-plugin";
import { createJsonFileDiscoveryStore } from "./json-file-discovery-store.js";
import { refreshModelDiscovery, type DiscoveryRefreshResult } from "./discovery-coordinator.js";
import { shouldRunInitialDiscovery } from "./autodiscovery-policy.js";
import { contract } from "./contract.js";
import { createOllamaCatalogReader } from "./ollama-catalog-reader.js";
import { createOllamaTelemetryBootstrap } from "./ollama-telemetry.js";
import { createDecisionClient } from "./decision-client.js";
import { deriveTaskProfile } from "./task-profile.js";

type AccePluginConfig = {
  enabled?: boolean;
  mode?: "shadow" | "adaptive";
  decisionServiceUrl?: string;
  decisionServiceToken?: string;
  allowExternalNetwork?: boolean;
  maxCloudCostUsd?: number;
  autoDiscoverOnStartup?: boolean;
  ollamaUrl?: string;
  inventoryPath?: string;
};

function isEnabled(config: AccePluginConfig): boolean {
  // OpenClaw controls whether this plugin is loaded via plugins.entries.<id>.enabled.
  // api.pluginConfig contains only the plugin-specific config object, so `enabled`
  // is an optional plugin-level kill switch rather than a mirror of host enablement.
  return config.enabled !== false && (config.mode === undefined || config.mode === "shadow" || config.mode === "adaptive");
}

function configuredOllamaUrl(config: AccePluginConfig): string {
  return config.ollamaUrl?.trim() || process.env.ACCE_OLLAMA_URL?.trim() || "http://127.0.0.1:11434";
}

function resolveStorePath(rawPath: string): string {
  const expanded = rawPath.startsWith("~/") ? join(homedir(), rawPath.slice(2)) : rawPath;
  if (!isAbsolute(expanded)) {
    throw new TypeError("discovery inventory path must be absolute or start with ~/");
  }
  return resolve(expanded);
}

function safeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default defineFeaturePlugin({
  contract,
  name: "ACCE Optimizer",
  description:
    "Governed adaptive model routing, cost optimization, quota preservation, and context-aware execution planning for OpenClaw.",
  setup(api) {
    const config = (api.pluginConfig ?? {}) as AccePluginConfig;

    const decisionClient = createDecisionClient({
      baseUrl: config.decisionServiceUrl ?? process.env.ACCE_DECISION_SERVICE_URL,
      bearerToken: config.decisionServiceToken ?? process.env.ACCE_DECISION_TOKEN,
    });

    api.on("before_model_resolve", async (event) => {
      if (!isEnabled(config)) return;
      const mode = config.mode ?? "adaptive";
      if (mode === "shadow") {
        api.logger.info(JSON.stringify({
          event: "acce.decision.shadow_observation",
          hook: "before_model_resolve",
          promptPresent: typeof event.prompt === "string" && event.prompt.length > 0,
        }));
        return;
      }
      if (!decisionClient.configured) {
        api.logger.warn(JSON.stringify({
          event: "acce.decision.unavailable",
          reason: "decision-service-not-configured",
          action: "keeping-openclaw-default-model",
        }));
        return;
      }

      // Never send prompt, attachments, history, or session identifiers to the bridge.
      try {
        const taskProfile = deriveTaskProfile(event.prompt);
        const decision = await decisionClient.decide({
          request_id: "openclaw-model-selection",
          task_class: "general",
          summary: taskProfile.summary,
          required_capabilities: ["text-generation"],
          profile: "balanced_local_first",
          constraints: {
            privacy_level: "unknown",
            external_network_allowed: config.allowExternalNetwork === true,
            max_cloud_cost_usd: config.maxCloudCostUsd ?? 0,
            max_latency_ms: 120000,
            min_quality_score: 0,
            search_budget: { max_candidate_routes: 100 },
            quota_budget: { remaining_fraction: 1 },
          },
          urgency: taskProfile.urgency,
          governance: { validation_required: true },
        });
        if (decision?.status !== "execution_plan_ready" ||
            !decision.providerOverride || !decision.modelOverride) {
          api.logger.info(JSON.stringify({
            event: "acce.decision.no_override",
            decisionId: decision?.decision_id ?? null,
            decisionState: decision?.decision_state ?? null,
          }));
          return;
        }
        api.logger.info(JSON.stringify({
          event: "acce.decision.route_selected",
          decisionId: decision.decision_id ?? null,
          routeId: decision.selected_route?.route_id ?? null,
          provider: decision.providerOverride,
          model: decision.modelOverride,
          engine: decision.engine ?? "adaptive_graph",
          policyMode: decision.policy_mode ?? "unknown",
        }));
        return {
          providerOverride: decision.providerOverride,
          modelOverride: decision.modelOverride,
        };
      } catch (error) {
        api.logger.warn(JSON.stringify({
          event: "acce.decision.failed",
          error: safeError(error),
          action: "keeping-openclaw-default-model",
        }));
        return;
      }
    });

    const syncDiscoveryEvidence = async (snapshot: DiscoveryRefreshResult["snapshot"]): Promise<void> => {
      if (!decisionClient.configured) return;
      const minimized = Object.fromEntries(Object.entries(snapshot).map(([key, model]) => [
        key,
        {
          providerId: model.providerId,
          modelId: model.modelId,
          productionEligible: model.productionEligible,
          telemetryStatus: model.telemetryStatus,
          ...(model.telemetry ? {
            telemetry: {
              capturedAt: model.telemetry.capturedAt,
              measurementId: model.telemetry.measurementId,
              metrics: {
                latencyMs: model.telemetry.metrics.latencyMs,
                available: model.telemetry.metrics.available,
              },
            },
          } : {}),
        },
      ]));
      try {
        await decisionClient.syncObservations(minimized);
      } catch (error) {
        // Telemetry remains safely persisted in the inventory; sync can retry
        // on the next refresh and never makes discovery itself fail.
        api.logger.warn(JSON.stringify({
          event: "acce.decision.observation_sync_failed",
          error: safeError(error),
        }));
      }
    };

    const defaultStorePath = () =>
      resolveStorePath(config.inventoryPath ?? "~/.openclaw/acce-optimizer-data/inventory.json");
    let activeRefresh: Promise<DiscoveryRefreshResult> | undefined;

    const refreshDiscovery = async (
      ollamaUrl: string,
      storePath: string,
      logProgress: (event: unknown) => void = (event) => api.logger.info(JSON.stringify(event)),
    ): Promise<DiscoveryRefreshResult> => {
      if (activeRefresh) return activeRefresh;
      const operation = refreshModelDiscovery({
        readers: [createOllamaCatalogReader({ baseUrl: ollamaUrl })],
        store: createJsonFileDiscoveryStore(storePath),
        bootstrapTelemetry: createOllamaTelemetryBootstrap({ baseUrl: ollamaUrl }),
        onProgress(progress) {
          logProgress({ event: "acce.discovery.refresh.progress", ...progress });
        },
      });
      activeRefresh = operation;
      try {
        const result = await operation;
        await syncDiscoveryEvidence(result.snapshot);
        return result;
      } finally {
        if (activeRefresh === operation) activeRefresh = undefined;
      }
    };

    // A background service runs only for a missing/empty inventory. Its
    // promise is deliberately not awaited by service startup, so Ollama
    // availability and model probes cannot delay the Gateway boot sequence.
    api.registerService({
      id: "acce-optimizer-autodiscovery",
      start() {
        if (!isEnabled(config) || config.autoDiscoverOnStartup === false) return;
        void (async () => {
          const storePath = defaultStorePath();
          const existing = await createJsonFileDiscoveryStore(storePath).load();
          await syncDiscoveryEvidence(existing);
          if (!shouldRunInitialDiscovery({
            enabled: isEnabled(config),
            autoDiscoverOnStartup: config.autoDiscoverOnStartup !== false,
            inventoryRecordCount: Object.keys(existing).length,
          })) {
            api.logger.info(JSON.stringify({
              event: "acce.discovery.startup.skipped",
              reason: "inventory-already-initialized",
              records: Object.keys(existing).length,
            }));
            return;
          }
          const result = await refreshDiscovery(configuredOllamaUrl(config), storePath);
          api.logger.info(JSON.stringify({
            event: "acce.discovery.startup.completed",
            discovered: result.discovered,
            added: result.added,
            telemetryCaptured: result.telemetryCaptured,
            telemetryPending: result.telemetryPending,
            productionEligible: result.productionEligible,
          }));
        })().catch((error: unknown) => {
          api.logger.warn(JSON.stringify({
            event: "acce.discovery.startup.failed",
            error: safeError(error),
            retry: "manual refresh or next Gateway startup",
          }));
        });
      },
    });

    api.registerCli((ctx) => {
      const root = ctx.program
        .command("acce-optimizer")
        .description("ACCE Optimizer governed model discovery");
      root
        .command("discovery-refresh")
        .description("Refresh the configured Ollama catalog and persist inventory")
        .requiredOption("--ollama-url <url>", "Explicit Ollama base URL (for example http://localhost:11434)")
        .requiredOption("--store <absolute-path>", "Absolute path for the private discovery inventory JSON")
        .action(async (options: { ollamaUrl: string; store: string }) => {
          const storePath = resolveStorePath(options.store);
          const result = await refreshDiscovery(options.ollamaUrl, storePath, (event) => {
            ctx.logger.info(JSON.stringify(event));
          });
          ctx.logger.info(JSON.stringify({
            event: "acce.discovery.refresh.completed",
            discovered: result.discovered,
            added: result.added,
            refreshed: result.refreshed,
            telemetryCaptured: result.telemetryCaptured,
            telemetryPending: result.telemetryPending,
            productionEligible: result.productionEligible,
          }));
          process.stdout.write(JSON.stringify({
            discovered: result.discovered,
            added: result.added,
            refreshed: result.refreshed,
            telemetryCaptured: result.telemetryCaptured,
            telemetryPending: result.telemetryPending,
            productionEligible: result.productionEligible,
            store: storePath,
          }, null, 2) + "\n");
        });
    }, {
      commands: ["acce-optimizer"],
      descriptors: [{
        name: "acce-optimizer",
        description: "ACCE Optimizer governed model discovery",
        hasSubcommands: true,
      }],
    });

    return {
      async "refresh-discovery"() {
        if (!isEnabled(config)) {
          throw new Error("ACCE Optimizer is disabled.");
        }
        const result = await refreshDiscovery(configuredOllamaUrl(config), defaultStorePath());
        api.logger.info(JSON.stringify({
          event: "acce.discovery.dashboard-refresh.completed",
          discovered: result.discovered,
          added: result.added,
          refreshed: result.refreshed,
          telemetryCaptured: result.telemetryCaptured,
          telemetryPending: result.telemetryPending,
          productionEligible: result.productionEligible,
        }));
        return {
          discovered: result.discovered,
          added: result.added,
          refreshed: result.refreshed,
          telemetryCaptured: result.telemetryCaptured,
          telemetryPending: result.telemetryPending,
          productionEligible: result.productionEligible,
        };
      },
    };
  },
});
