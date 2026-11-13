import { describe, expect, it } from "vitest";
import {
  markModelUserAdded,
  modelKey,
  recordModelTelemetry,
  upsertDiscoveredModel,
  type DiscoverySnapshot,
  type ModelObservation,
} from "./discovery.js";

const firstObservation: ModelObservation = {
  providerId: "OpenAI",
  modelId: "gpt-test",
  source: "openclaw",
  observedAt: "2026-10-19T10:00:00Z",
  capabilities: ["chat"],
  metadata: { catalog: "configured" },
};

describe("governed model discovery", () => {
  it("normalizes provider identity but preserves the model identifier", () => {
    expect(modelKey(" OpenAI ", "gpt-test")).toBe("openai/gpt-test");
  });

  it("discovers a model without promoting it to a route or production", () => {
    const snapshot = upsertDiscoveredModel({}, firstObservation);
    const model = snapshot["openai/gpt-test"];
    expect(model.lifecycle).toBe("DISCOVERED");
    expect(model.telemetryStatus).toBe("pending");
    expect(model.userAdded).toBe(false);
    expect(model.productionEligible).toBe(false);
  });

  it("merges repeat discovery and preserves telemetry and explicit user intent", () => {
    let snapshot: DiscoverySnapshot = upsertDiscoveredModel({}, firstObservation);
    snapshot = recordModelTelemetry(snapshot, "openai/gpt-test", {
      capturedAt: "2026-10-19T10:05:00Z",
      measurementId: "measurement-001",
      metrics: { latencyMs: 42, available: true },
    });
    snapshot = markModelUserAdded(snapshot, "openai/gpt-test");
    snapshot = upsertDiscoveredModel(snapshot, {
      ...firstObservation,
      source: "configured",
      observedAt: "2026-10-19T11:00:00Z",
      capabilities: ["tools"],
      metadata: { sourceHint: "settings" },
    });

    const model = snapshot["openai/gpt-test"];
    expect(model.firstSeenAt).toBe("2026-10-19T10:00:00Z");
    expect(model.lastSeenAt).toBe("2026-10-19T11:00:00Z");
    expect(model.sources).toEqual(["configured", "openclaw"]);
    expect(model.capabilities).toEqual(["chat", "tools"]);
    expect(model.telemetry?.measurementId).toBe("measurement-001");
    expect(model.telemetry?.metrics.latencyMs).toBe(42);
    expect(model.userAdded).toBe(true);
    expect(model.lifecycle).toBe("USER_ADDED");
    expect(model.productionEligible).toBe(false);
  });

  it("marks telemetry captured but does not imply user consent or production eligibility", () => {
    const discovered = upsertDiscoveredModel({}, firstObservation);
    const captured = recordModelTelemetry(discovered, "openai/gpt-test", {
      capturedAt: "2026-10-19T10:05:00Z",
      measurementId: "measurement-002",
      metrics: { latencyMs: 55 },
    });
    const model = captured["openai/gpt-test"];
    expect(model.lifecycle).toBe("TELEMETRY_CAPTURED");
    expect(model.userAdded).toBe(false);
    expect(model.productionEligible).toBe(false);
  });

  it("rejects invalid telemetry and unknown model keys", () => {
    const snapshot = upsertDiscoveredModel({}, firstObservation);
    expect(() => recordModelTelemetry(snapshot, "missing/model", {
      capturedAt: "2026-10-19T10:05:00Z",
      measurementId: "measurement-003",
      metrics: {},
    })).toThrow(/unknown discovered model/);
    expect(() => upsertDiscoveredModel({}, {
      ...firstObservation,
      observedAt: "not-a-timestamp",
    })).toThrow(/valid timestamp/);
    expect(() => recordModelTelemetry(snapshot, "openai/gpt-test", {
      capturedAt: "2026-10-19T10:05:00Z",
      measurementId: "measurement-004",
      metrics: { latencyMs: Number.NaN },
    })).toThrow(/must be finite/);
  });
});
