import { describe, expect, it } from "vitest";
import { isModelOverrideAllowed } from "./openclaw-override-policy.js";

describe("OpenClaw model override policy", () => {
  const config = (llm: Record<string, unknown>) => ({ plugins: { entries: { "acce-optimizer": { llm } } } });

  it("requires explicit operator opt-in", () => {
    expect(isModelOverrideAllowed(config({}), "acce-optimizer", "local", "model-a")).toBe(false);
    expect(isModelOverrideAllowed(config({ allowModelOverride: true }), "acce-optimizer", "local", "model-a")).toBe(true);
  });

  it("enforces the canonical provider/model allowlist when configured", () => {
    expect(isModelOverrideAllowed(config({ allowModelOverride: true, allowedModels: ["local/model-a"] }), "acce-optimizer", "local", "model-a")).toBe(true);
    expect(isModelOverrideAllowed(config({ allowModelOverride: true, allowedModels: ["local/model-a"] }), "acce-optimizer", "cloud", "model-b")).toBe(false);
  });

  it("fails closed for malformed allowlists or missing config", () => {
    expect(isModelOverrideAllowed(config({ allowModelOverride: true, allowedModels: ["local/model-a", 1] }), "acce-optimizer", "local", "model-a")).toBe(false);
    expect(isModelOverrideAllowed({}, "acce-optimizer", "local", "model-a")).toBe(false);
  });
});
