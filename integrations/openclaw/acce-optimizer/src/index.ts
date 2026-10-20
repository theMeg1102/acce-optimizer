import { homedir } from "node:os";
import { join } from "node:path";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { createJsonFileDiscoveryStore } from "./json-file-discovery-store.js";
import { refreshModelDiscovery } from "./discovery-coordinator.js";
import { createOllamaCatalogReader } from "./ollama-catalog-reader.js";

type AccePluginConfig = {
  enabled?: boolean;
  mode?: "shadow";
};

function isEnabled(config: Record<string, unknown>): boolean {
  return config.enabled === true && (config.mode === undefined || config.mode === "shadow");
}

export default definePluginEntry({
  id: "acce-optimizer",
  name: "ACCE Optimizer",
  description:
    "Governed adaptive model routing, cost optimization, quota preservation, and context-aware execution planning for OpenClaw.",
  register(api) {
    const config = api.pluginConfig as AccePluginConfig;

    api.on("before_model_resolve", (event, ctx) => {
      if (!isEnabled(config)) {
        return;
      }

      api.logger.info(
        JSON.stringify({
          mode: "shadow",
          hook: "before_model_resolve",
          sessionKey: ctx.sessionKey ?? null,
          runId: ctx.runId ?? null,
          promptPresent: typeof event.prompt === "string" && event.prompt.length > 0,
        }),
      );

      // Shadow mode is intentionally non-mutating. ACCE does not override
      // provider or model selection until the authoritative integration gate
      // is explicitly enabled in a future phase.
      return;
    });

    // Explicit, operator-triggered discovery. The store path is required so
    // the command never guesses where durable inventory should be written.
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
          const storePath = options.store.startsWith("~/")
            ? join(homedir(), options.store.slice(2))
            : options.store;
          const result = await refreshModelDiscovery({
            readers: [createOllamaCatalogReader({ baseUrl: options.ollamaUrl })],
            store: createJsonFileDiscoveryStore(storePath),
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
          }, null, 2) + "\\n");
        });
    }, {
      commands: ["acce-optimizer"],
      descriptors: [{
        name: "acce-optimizer",
        description: "ACCE Optimizer governed model discovery",
        hasSubcommands: true,
      }],
    });
  },
});
