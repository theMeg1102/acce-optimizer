import { describe, expect, it } from "vitest";
import { readConfiguredRuntimeModels, sanitizeModelTelemetry } from "./openclaw-runtime-state.js";
describe("OpenClaw runtime state adapter", () => {
  it("extracts model metadata but never copies provider credentials", () => { const models = readConfiguredRuntimeModels({ models: { providers: { cloud: { apiKey: "never-copy-this", models: [{ id: "cloud-a", contextWindow: 128000, input: ["text", "image"], cost: { input: 1, output: 2 } }] }, local: { models: [{ id: "local-b", contextWindow: 32000 }] } } } }); expect(models).toHaveLength(2); expect(models[0]).toMatchObject({ providerId: "cloud", modelId: "cloud-a", contextWindow: 128000, cost: { input: 1, output: 2 } }); expect(JSON.stringify(models)).not.toContain("never-copy-this"); });
  it("inherits effective provider context defaults and omits unsupported tiered pricing", () => {
    const models = readConfiguredRuntimeModels({ models: { providers: {
      inherited: { contextWindow: 64000, contextTokens: 16000, maxTokens: 2048, models: [{ id: "inherited-model" }] },
      tiered: { models: [{ id: "tiered-model", cost: { input: 1, output: 2, tieredPricing: [{ input: 2, output: 4 }] } }] },
    } } });
    expect(models.find((model) => model.modelId === "inherited-model")).toMatchObject({ contextWindow: 64000, contextTokens: 16000, maxTokens: 2048 });
    expect(models.find((model) => model.modelId === "tiered-model")?.cost).toBeUndefined();
  });
  it("does not invent a catalog when effective config has no providers", () => { expect(readConfiguredRuntimeModels({ models: {} })).toEqual([]); expect(readConfiguredRuntimeModels(null)).toEqual([]); });
  it("sanitizes telemetry, preserves effective context budget, and drops prompt/response text", () => { const result = sanitizeModelTelemetry({ provider: "cloud", model: "model-a", durationMs: 1200, outcome: "success", contextTokenBudget: 8192, prompt: "private", response: "private response", usage: { input: 10, output: 4, total: 14 }, upstreamRequestIdHash: "hash-123" }); expect(result).toEqual({ providerId: "cloud", modelId: "model-a", durationMs: 1200, outcome: "success", requestIdHash: "hash-123", inputTokens: 10, outputTokens: 4, totalTokens: 14, contextTokenBudget: 8192 }); expect(JSON.stringify(result)).not.toContain("private"); });
});
