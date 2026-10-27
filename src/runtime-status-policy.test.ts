import { describe, expect, it } from "vitest";
import {
  isKnownLocalProvider,
  isRuntimeStatusFresh,
  runtimeOverrideBlockReason,
} from "./runtime-status-policy.js";

const NOW = Date.parse("2026-10-27T12:00:00.000Z");
const MAX_AGE = 300_000;
const freshStatus = {
  modelsCapturedAt: new Date(NOW - 1_000).toISOString(),
  usageCapturedAt: new Date(NOW - 2_000).toISOString(),
  models: [
    { providerId: "ollama", modelId: "qwen3:8b", available: true as const },
    { providerId: "openai", modelId: "gpt-test", available: true as const },
    { providerId: "openai", modelId: "gpt-down", available: false as const },
  ],
  usage: [{ providerId: "openai", remainingFraction: 0.4 }],
};

describe("runtime status authorization policy", () => {
  it("rejects a missing snapshot", () => {
    expect(isRuntimeStatusFresh(undefined, NOW, MAX_AGE)).toBe(false);
    expect(runtimeOverrideBlockReason(undefined, "ollama", "qwen3:8b", { now: NOW, maxAgeMs: MAX_AGE }))
      .toBe("runtime-status-missing-or-stale");
  });

  it("rejects stale, invalid, and implausibly future model snapshots", () => {
    expect(isRuntimeStatusFresh({ ...freshStatus, modelsCapturedAt: new Date(NOW - MAX_AGE - 1).toISOString() }, NOW, MAX_AGE)).toBe(false);
    expect(isRuntimeStatusFresh({ ...freshStatus, modelsCapturedAt: "not-a-date" }, NOW, MAX_AGE)).toBe(false);
    expect(isRuntimeStatusFresh({ ...freshStatus, modelsCapturedAt: new Date(NOW + 60_000).toISOString() }, NOW, MAX_AGE)).toBe(false);
  });

  it("requires an exact model row with available=true", () => {
    expect(runtimeOverrideBlockReason(freshStatus, "ollama", "qwen3:8b", { now: NOW, maxAgeMs: MAX_AGE })).toBeUndefined();
    expect(runtimeOverrideBlockReason(freshStatus, "ollama", "missing", { now: NOW, maxAgeMs: MAX_AGE })).toBe("model-not-confirmed-available");
    expect(runtimeOverrideBlockReason(freshStatus, "openai", "gpt-down", { now: NOW, maxAgeMs: MAX_AGE })).toBe("model-not-confirmed-available");
  });

  it("requires fresh provider usage only when the selected route depends on quota", () => {
    expect(runtimeOverrideBlockReason(freshStatus, "ollama", "qwen3:8b", {
      now: NOW, maxAgeMs: MAX_AGE, requireFreshProviderUsage: false,
    })).toBeUndefined();
    expect(runtimeOverrideBlockReason(freshStatus, "openai", "gpt-test", {
      now: NOW, maxAgeMs: MAX_AGE, requireFreshProviderUsage: true,
    })).toBeUndefined();
  });

  it("rejects remote quota-dependent routes when usage is missing or stale", () => {
    expect(runtimeOverrideBlockReason({ ...freshStatus, usageCapturedAt: "" }, "openai", "gpt-test", {
      now: NOW, maxAgeMs: MAX_AGE, requireFreshProviderUsage: true,
    })).toBe("provider-usage-missing-or-stale");
    expect(runtimeOverrideBlockReason({ ...freshStatus, usage: [] }, "openai", "gpt-test", {
      now: NOW, maxAgeMs: MAX_AGE, requireFreshProviderUsage: true,
    })).toBe("provider-usage-missing-invalid-or-exhausted");
    expect(runtimeOverrideBlockReason({ ...freshStatus, usage: [{ providerId: "openai", remainingFraction: 0 }] }, "openai", "gpt-test", {
      now: NOW, maxAgeMs: MAX_AGE, requireFreshProviderUsage: true,
    })).toBe("provider-usage-missing-invalid-or-exhausted");
    expect(runtimeOverrideBlockReason({ ...freshStatus, usageCapturedAt: new Date(NOW - MAX_AGE - 1).toISOString() }, "openai", "gpt-test", {
      now: NOW, maxAgeMs: MAX_AGE, requireFreshProviderUsage: true,
    })).toBe("provider-usage-missing-or-stale");
  });

  it("recognizes only explicitly known local provider IDs for quota policy", () => {
    expect(isKnownLocalProvider("ollama")).toBe(true);
    expect(isKnownLocalProvider("LMStudio")).toBe(true);
    expect(isKnownLocalProvider("openai")).toBe(false);
  });
});
