import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

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

      api.logger.info({
        mode: "shadow",
        hook: "before_model_resolve",
        sessionKey: ctx.sessionKey ?? null,
        runId: ctx.runId ?? null,
        promptPresent: typeof event.prompt === "string" && event.prompt.length > 0,
      });

      // Shadow mode is intentionally non-mutating. ACCE does not override
      // provider or model selection until the authoritative integration gate
      // is explicitly enabled in a future phase.
      return;
    });
  },
});
