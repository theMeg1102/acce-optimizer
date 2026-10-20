import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { defineFeaturePlugin } from "openclaw/plugin-sdk/feature-plugin";
import { createJsonFileDiscoveryStore } from "./json-file-discovery-store.js";
import { refreshModelDiscovery, type DiscoveryRefreshResult } from "./discovery-coordinator.js";
import { shouldRunInitialDiscovery } from "./autodiscovery-policy.js";
import { contract } from "./contract.js";
import { createOllamaCatalogReader } from "./ollama-catalog-reader.js";
import { createOllamaTelemetryBootstrap } from "./ollama-telemetry.js";

type AccePluginConfig = {
  enabled?: boolean;
  mode?: "shadow";
  autoDiscoverOnStartup?: boolean;
  ollamaUrl?: string;
  inventoryPath?: string;
};

function isEnabled(config: AccePluginConfig): boolean {
  return config.enabled === true && (config.mode === undefined || config.mode === "shadow");
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

    api.on("before_model_resolve", (event, ctx) => {
      if (!isEnabled(config)) return;
      api.logger.info(JSON.stringify({
        mode: "shadow",
        hook: "before_model_resolve",
        sessionKey: ctx.sessionKey ?? null,
        runId: ctx.runId ?? null,
        promptPresent: typeof event.prompt === "string" && event.prompt.length > 0,
      }));
      // Shadow mode is intentionally non-mutating; no provider/model override.
    });

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
        return await operation;
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
