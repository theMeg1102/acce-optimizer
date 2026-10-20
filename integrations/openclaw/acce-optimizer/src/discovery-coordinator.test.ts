import { describe, expect, it } from "vitest";
import {
  createMemoryDiscoveryStore,
  refreshModelDiscovery,
  type CatalogReader,
} from "./discovery-coordinator.js";
import {
  markModelUserAdded,
  recordModelTelemetry,
  upsertDiscoveredModel,
} from "./discovery.js";

const instant = new Date("2026-10-19T12:00:00Z");
const reader: CatalogReader = {
  source: "openclaw",
  async listModels() {
    return [
      { providerId: "local", modelId: "model-a", displayName: "Model A" },
      { providerId: "remote", modelId: "model-b" },
    ];
  },
};

describe("discovery coordinator", () => {
  it("refreshes an authorized reader, captures supplied evidence and persists without enabling production", async () => {
    const store = createMemoryDiscoveryStore();
    const result = await refreshModelDiscovery({
      readers: [reader],
      store,
      now: () => instant,
      async bootstrapTelemetry(model) {
        if (model.modelId === "model-a") {
          return {
            capturedAt: instant.toISOString(),
            measurementId: "probe-model-a",
            metrics: { available: true, latencyMs: 19 },
          };
        }
        return undefined;
      },
    });

    expect(result.added).toBe(2);
    expect(result.refreshed).toBe(0);
    expect(result.telemetryCaptured).toBe(1);
    expect(result.telemetryPending).toBe(1);
    expect(result.productionEligible).toBe(0);
    expect(store.inspect()["local/model-a"].telemetry?.metrics.latencyMs).toBe(19);
    expect(store.inspect()["remote/model-b"].telemetryStatus).toBe("pending");
    expect(Object.values(store.inspect()).every((model) => model.productionEligible === false)).toBe(true);
  });

  it("retains historical telemetry and user-added state on refresh", async () => {
    let snapshot = upsertDiscoveredModel({}, {
      providerId: "local",
      modelId: "model-a",
      source: "openclaw",
      observedAt: "2026-10-18T12:00:00Z",
    });
    snapshot = recordModelTelemetry(snapshot, "local/model-a", {
      capturedAt: "2026-10-18T12:01:00Z",
      measurementId: "historic-measurement",
      metrics: { latencyMs: 31 },
    });
    snapshot = markModelUserAdded(snapshot, "local/model-a");
    const store = createMemoryDiscoveryStore(snapshot);
    const result = await refreshModelDiscovery({
      readers: [reader],
      store,
      now: () => instant,
      async bootstrapTelemetry() {
        throw new Error("existing telemetry must not be re-captured");
      },
    });

    const model = result.snapshot["local/model-a"];
    expect(result.added).toBe(1);
    expect(result.refreshed).toBe(1);
    expect(model.firstSeenAt).toBe("2026-10-18T12:00:00Z");
    expect(model.telemetry?.measurementId).toBe("historic-measurement");
    expect(model.telemetry?.metrics.latencyMs).toBe(31);
    expect(model.userAdded).toBe(true);
    expect(model.productionEligible).toBe(false);
  });

  it("does not mark failed telemetry as captured and does not abort discovery", async () => {
    const store = createMemoryDiscoveryStore();
    const result = await refreshModelDiscovery({
      readers: [reader],
      store,
      now: () => instant,
      async bootstrapTelemetry() {
        throw new Error("provider unavailable");
      },
    });
    expect(result.discovered).toBe(2);
    expect(result.telemetryCaptured).toBe(0);
    expect(result.telemetryPending).toBe(2);
  });

  it("does not save a partial snapshot when catalog discovery fails", async () => {
    const store = createMemoryDiscoveryStore();
    const failingReader: CatalogReader = {
      source: "custom",
      async listModels() {
        throw new Error("catalog unavailable");
      },
    };
    await expect(refreshModelDiscovery({
      readers: [failingReader],
      store,
      now: () => instant,
    })).rejects.toThrow("catalog unavailable");
    expect(store.inspect()).toEqual({});
  });
  it("emits ordered progress events without enabling production", async () => {
    const store = createMemoryDiscoveryStore();
    const events: string[] = [];
    const result = await refreshModelDiscovery({
      readers: [reader],
      store,
      now: () => instant,
      async bootstrapTelemetry(model) {
        if (model.modelId === "model-a") {
          return {
            capturedAt: instant.toISOString(),
            measurementId: "progress-model-a",
            metrics: { available: true, latencyMs: 12 },
          };
        }
        throw new Error("probe unavailable");
      },
      onProgress(event) {
        events.push(event.type);
      },
    });

    expect(events).toEqual([
      "catalog_started",
      "catalog_completed",
      "telemetry_started",
      "telemetry_completed",
      "telemetry_started",
      "telemetry_failed",
      "refresh_completed",
    ]);
    expect(result.telemetryCaptured).toBe(1);
    expect(result.telemetryPending).toBe(1);
    expect(result.productionEligible).toBe(0);
    expect(Object.values(result.snapshot).every(
      (model) => model.productionEligible === false,
    )).toBe(true);
  });


});
