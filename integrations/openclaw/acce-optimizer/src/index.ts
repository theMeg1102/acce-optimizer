import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { createJsonFileDiscoveryStore } from "./json-file-discovery-store.js";
import { refreshModelDiscovery, type DiscoveryRefreshResult } from "./discovery-coordinator.js";
import { shouldRunInitialDiscovery } from "./autodiscovery-policy.js";
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

function panelHtml(): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ACCE Optimizer</title>
<style>
:root{color-scheme:light dark;font:14px system-ui,sans-serif}
body{margin:0;padding:24px;max-width:760px}
main{border:1px solid color-mix(in srgb,currentColor 18%,transparent);border-radius:12px;padding:20px}
h1{font-size:1.35rem;margin:0 0 8px}
p{line-height:1.55}
button{padding:10px 14px;border-radius:8px;border:1px solid currentColor;cursor:pointer;font:inherit}
button:disabled{opacity:.55;cursor:wait}
#result{white-space:pre-wrap;margin-top:16px}
small{opacity:.75}
</style>
</head>
<body>
<main>
<h1>ACCE Optimizer</h1>
<p>Discover and recalibrate the configured Ollama model catalog. On first startup, ACCE runs discovery automatically when the inventory is empty, unless automatic startup discovery is disabled in plugin settings.</p>
<p>Manual refresh updates existing records and retries telemetry that is still pending. Model production eligibility remains disabled.</p>
<button id="refresh" type="button">Recalibrate discovery now</button>
<div id="result" role="status" aria-live="polite">Ready. Refresh runs against the configured Ollama endpoint.</div>
<p><small>Configure the Ollama URL and startup discovery under OpenClaw → Settings → Plugins → ACCE Optimizer.</small></p>
</main>
<script>
const button=document.getElementById("refresh");
const result=document.getElementById("result");
button.addEventListener("click",async()=>{
  button.disabled=true;
  result.textContent="Discovery running…";
  try{
    const response=await fetch("/plugins/acce-optimizer/refresh",{method:"POST",credentials:"same-origin",headers:{"accept":"application/json"}});
    const payload=await response.json();
    if(!response.ok||!payload.ok) throw new Error(payload.message||"Refresh failed. Check Gateway logs.");
    result.textContent=[
      "Discovery completed",
      "Models discovered: "+payload.discovered,
      "New records: "+payload.added,
      "Existing records refreshed: "+payload.refreshed,
      "Telemetry captured: "+payload.telemetryCaptured,
      "Telemetry pending: "+payload.telemetryPending,
      "Production eligible: "+payload.productionEligible
    ].join("\\n");
  }catch(error){
    result.textContent=error instanceof Error?error.message:"Refresh failed. Check Gateway logs.";
  }finally{button.disabled=false;}
});
</script>
</body>
</html>`;
}

export default definePluginEntry({
  id: "acce-optimizer",
  name: "ACCE Optimizer",
  description:
    "Governed adaptive model routing, cost optimization, quota preservation, and context-aware execution planning for OpenClaw.",
  register(api) {
    const config = (api.pluginConfig ?? {}) as AccePluginConfig;

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

    // First-run discovery is background service work: connection or catalog
    // errors are logged and retried on a later startup or manual refresh, never
    // allowed to prevent the Gateway from starting.
    api.registerService({
      id: "acce-optimizer-autodiscovery",
      async start() {
        if (!isEnabled(config) || config.autoDiscoverOnStartup === false) return;
        try {
          const storePath = defaultStorePath();
          const store = createJsonFileDiscoveryStore(storePath);
          const existing = await store.load();
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
        } catch (error) {
          api.logger.warn(JSON.stringify({
            event: "acce.discovery.startup.failed",
            error: safeError(error),
            retry: "manual refresh or next Gateway startup",
          }));
        }
      },
    });

    // A small authenticated Control UI panel gives operators a one-click
    // refresh without exposing inventory contents or allowing production routes.
    api.session.controls.registerControlUiDescriptor({
      id: "acce-optimizer-discovery",
      surface: "tab",
      label: "ACCE Optimizer",
      description: "Model discovery and telemetry refresh",
      slug: "acce-optimizer",
      path: "/plugins/acce-optimizer/panel",
      icon: "refresh-cw",
      group: "control",
      order: 80,
      requiredScopes: ["operator.admin"],
    });

    api.registerHttpRoute({
      path: "/plugins/acce-optimizer",
      match: "prefix",
      auth: "gateway",
      handler: async (req, res) => {
        const pathname = new URL(req.url ?? "/", "http://localhost").pathname;
        if (req.method === "GET" && pathname === "/plugins/acce-optimizer/panel") {
          res.writeHead(200, {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
          });
          res.end(panelHtml());
          return true;
        }
        if (req.method === "POST" && pathname === "/plugins/acce-optimizer/refresh") {
          try {
            if (!isEnabled(config)) {
              res.writeHead(409, { "content-type": "application/json; charset=utf-8" });
              res.end(JSON.stringify({ ok: false, message: "ACCE Optimizer is disabled." }));
              return true;
            }
            const storePath = defaultStorePath();
            const result = await refreshDiscovery(configuredOllamaUrl(config), storePath);
            res.writeHead(200, {
              "content-type": "application/json; charset=utf-8",
              "cache-control": "no-store",
              "x-content-type-options": "nosniff",
            });
            res.end(JSON.stringify({
              ok: true,
              discovered: result.discovered,
              added: result.added,
              refreshed: result.refreshed,
              telemetryCaptured: result.telemetryCaptured,
              telemetryPending: result.telemetryPending,
              productionEligible: result.productionEligible,
            }));
          } catch (error) {
            api.logger.warn(JSON.stringify({
              event: "acce.discovery.dashboard-refresh.failed",
              error: safeError(error),
            }));
            res.writeHead(500, { "content-type": "application/json; charset=utf-8" });
            res.end(JSON.stringify({
              ok: false,
              message: "Refresh failed. Check Gateway logs and the configured Ollama URL.",
            }));
          }
          return true;
        }
        return false;
      },
    });

    // Explicit, operator-triggered CLI discovery remains available for scripts.
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
