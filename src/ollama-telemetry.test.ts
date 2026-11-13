import { describe, expect, it, vi } from "vitest";
import { upsertDiscoveredModel } from "./discovery.js";
import { createOllamaTelemetryBootstrap } from "./ollama-telemetry.js";

const instant = new Date("2026-10-19T19:00:00.000Z");

function model(capabilities: string[]) {
  return upsertDiscoveredModel({}, {
    providerId: "ollama",
    modelId: "test-model",
    source: "ollama",
    observedAt: instant.toISOString(),
    capabilities,
  })["ollama/test-model"];
}

function response(status: number, payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("Ollama initial telemetry", () => {
  it("captures minimal generation latency and counts without storing response text", async () => {
    const fetchImpl = vi.fn(async (_url: string | URL, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toMatchObject({
        prompt: "Reply with OK.",
        stream: false,
        options: { num_predict: 1 },
      });
      return response(200, {
        response: "private generated content",
        total_duration: 120,
        load_duration: 20,
        prompt_eval_count: 4,
        eval_count: 1,
        eval_duration: 50,
      });
    });
    const bootstrap = createOllamaTelemetryBootstrap({
      baseUrl: "http://localhost:11434",
      fetchImpl,
      now: () => instant,
    });

    const evidence = await bootstrap(model(["completion"]));
    expect(evidence).toMatchObject({
      capturedAt: instant.toISOString(),
      metrics: {
        available: true,
        probeType: "generation",
        endpoint: "/api/generate",
        total_duration: 120,
        eval_count: 1,
      },
    });
    expect(evidence?.measurementId).toMatch(/^ollama-probe-/);
    expect(JSON.stringify(evidence)).not.toContain("private generated content");
  });

  it("uses a 90-second default timeout while allowing explicit overrides", async () => {
    const timeoutSpy = vi.spyOn(globalThis, "setTimeout");
    try {
      const bootstrap = createOllamaTelemetryBootstrap({
        baseUrl: "http://localhost:11434",
        fetchImpl: async () => response(200, {
          response: "OK",
          done: true,
        }),
      });

      await bootstrap(model(["completion"]));

      expect(timeoutSpy).toHaveBeenCalledWith(
        expect.any(Function),
        90000,
      );
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("captures embedding dimensions without persisting the vector", async () => {
    const fetchImpl = vi.fn(async (_url: string | URL, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toMatchObject({
        input: "ACCE telemetry probe",
      });
      return response(200, { embeddings: [[0.1, 0.2, 0.3]] });
    });
    const bootstrap = createOllamaTelemetryBootstrap({
      baseUrl: "http://localhost:11434",
      fetchImpl,
      now: () => instant,
    });

    const evidence = await bootstrap(model(["embedding"]));
    expect(evidence?.metrics).toMatchObject({
      available: true,
      probeType: "embedding",
      endpoint: "/api/embed",
      embeddingDimensions: 3,
    });
    expect(JSON.stringify(evidence)).not.toContain("0.1");
  });

  it("leaves models with unknown capabilities pending", async () => {
    const fetchImpl = vi.fn();
    const bootstrap = createOllamaTelemetryBootstrap({
      baseUrl: "http://localhost:11434",
      fetchImpl,
    });
    expect(await bootstrap(model([]))).toBeUndefined();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects failed probes so the coordinator can keep telemetry pending", async () => {
    const bootstrap = createOllamaTelemetryBootstrap({
      baseUrl: "http://localhost:11434",
      fetchImpl: async () => response(503, {}),
    });
    await expect(bootstrap(model(["completion"]))).rejects.toThrow(/HTTP 503/);
  });

  it("rejects generation output without a response string", async () => {
    const bootstrap = createOllamaTelemetryBootstrap({
      baseUrl: "http://localhost:11434",
      fetchImpl: async () => response(200, {}),
    });
    await expect(bootstrap(model(["completion"]))).rejects.toThrow(
      /string response/,
    );
  });

  it("rejects malformed embedding output", async () => {
    const bootstrap = createOllamaTelemetryBootstrap({
      baseUrl: "http://localhost:11434",
      fetchImpl: async () => response(200, { embeddings: [] }),
    });
    await expect(bootstrap(model(["embedding"]))).rejects.toThrow(/embedding vector/);
  });
});
