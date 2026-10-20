import { Type } from "typebox";
import { defineFeatureContract } from "openclaw/plugin-sdk/feature-contract";

export const contract = defineFeatureContract({
  pluginId: "acce-optimizer",
  operations: {
    refreshDiscovery: {
      kind: "action",
      description: "Refresh the configured Ollama model catalog and retry pending telemetry.",
      input: Type.Object({}, { additionalProperties: false }),
      output: Type.Object({
        discovered: Type.Integer({ minimum: 0 }),
        added: Type.Integer({ minimum: 0 }),
        refreshed: Type.Integer({ minimum: 0 }),
        telemetryCaptured: Type.Integer({ minimum: 0 }),
        telemetryPending: Type.Integer({ minimum: 0 }),
        productionEligible: Type.Literal(0),
      }, { additionalProperties: false }),
    },
  },
  events: {},
});
