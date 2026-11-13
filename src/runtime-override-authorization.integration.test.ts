import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  readRuntimeStatus: vi.fn(),
  decide: vi.fn(),
  recordAndEvaluateWithId: vi.fn(),
  getSuccessfulTemplate: vi.fn(),
  recordDecision: vi.fn(),
  recordOutcome: vi.fn(),
}));

vi.mock("openclaw/plugin-sdk/feature-plugin", () => ({
  defineFeaturePlugin: (definition: unknown) => definition,
}));
vi.mock("./openclaw-cli-runtime-status.js", () => ({
  readOpenClawRuntimeStatus: mocks.readRuntimeStatus,
}));
vi.mock("./decision-client.js", () => ({
  createDecisionClient: () => ({
    configured: true,
    decide: mocks.decide,
    recordOutcome: vi.fn(),
    syncObservations: vi.fn(),
  }),
}));
vi.mock("./openclaw-runtime-state.js", () => ({
  readConfiguredRuntimeModels: () => [{ providerId: "ollama", modelId: "qwen3:8b" }],
  sanitizeModelTelemetry: () => ({}),
}));
vi.mock("./task-history-store.js", () => ({
  createTaskHistoryStore: () => ({
    recordAndEvaluateWithId: mocks.recordAndEvaluateWithId,
    getSuccessfulTemplate: mocks.getSuccessfulTemplate,
    recordDecision: mocks.recordDecision,
    recordOutcome: mocks.recordOutcome,
  }),
}));

import plugin from "./index.js";

function makeApi(allowModelOverride: boolean, allowedModels?: unknown[], mode: "adaptive" | "shadow" = "adaptive") {
  const hooks = new Map<string, (...args: any[]) => unknown>();
  const services: Array<{ id: string; start: () => void; stop?: () => void }> = [];
  const api = {
    pluginConfig: {
      mode,
      decisionServiceUrl: "http://127.0.0.1:18791",
      similarityHistoryPath: "/tmp/acce-override-authorization-test.json",
      runtimeStatusRefreshSeconds: 60,
    },
    config: {
      plugins: {
        entries: {
          "acce-optimizer": {
            llm: {
              allowModelOverride,
              ...(allowedModels === undefined ? {} : { allowedModels }),
            },
          },
        },
      },
    },
    registrationMode: "full",
    logger: { info: vi.fn(), warn: vi.fn() },
    on: (event: string, handler: (...args: any[]) => unknown) => hooks.set(event, handler),
    registerService: (service: { id: string; start: () => void; stop?: () => void }) => services.push(service),
    registerCli: vi.fn(),
  };
  return { api, hooks, services };
}

describe("ACCE override authorization integration", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.readRuntimeStatus.mockReset().mockResolvedValue({
      modelsCapturedAt: new Date(Date.now()).toISOString(),
      usageCapturedAt: new Date(Date.now()).toISOString(),
      models: [{ providerId: "ollama", modelId: "qwen3:8b", available: true }],
      usage: [],
    });
    mocks.decide.mockReset().mockResolvedValue({
      status: "execution_plan_ready",
      providerOverride: "ollama",
      modelOverride: "qwen3:8b",
      decision_id: "decision-auth-test",
      selected_route: { route_id: "local-route" },
      ranking_result: [],
    });
    mocks.recordAndEvaluateWithId.mockReset().mockResolvedValue({
      observationId: "observation-auth-test",
      consensus: {
        eligible: false,
        sampleSize: 1,
        matchingCount: 1,
        matchingFraction: 1,
        requiredMatches: 5,
        windowSizesEvaluated: [5],
        reason: "insufficient-history",
      },
    });
    mocks.getSuccessfulTemplate.mockReset().mockResolvedValue(undefined);
    mocks.recordDecision.mockReset().mockResolvedValue(true);
    mocks.recordOutcome.mockReset().mockResolvedValue(true);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  async function invokeHook(allowModelOverride: boolean, allowedModels?: unknown[], mode: "adaptive" | "shadow" = "adaptive") {
    const { api, hooks, services } = makeApi(allowModelOverride, allowedModels, mode);
    (plugin as unknown as { setup: (api: any) => void }).setup(api);
    const runtimeService = services.find((service) => service.id === "acce-optimizer-runtime-status");
    expect(runtimeService).toBeDefined();
    runtimeService?.start();
    await vi.advanceTimersByTimeAsync(15_000);
    const hook = hooks.get("before_model_resolve");
    expect(hook).toBeDefined();
    const result = await hook?.({ prompt: "write a short summary" }, {});
    runtimeService?.stop?.();
    return result;
  }

  it("never invokes the decision bridge or overrides a model in shadow mode", async () => {
    await expect(invokeHook(true, ["ollama/qwen3:8b"], "shadow")).resolves.toBeUndefined();
    expect(mocks.decide).not.toHaveBeenCalled();
    expect(mocks.recordAndEvaluateWithId).toHaveBeenCalledTimes(1);
  });

  it("keeps OpenClaw's default when the decision bridge fails", async () => {
    mocks.decide.mockRejectedValueOnce(new Error("isolated bridge unavailable"));
    await expect(invokeHook(true, ["ollama/qwen3:8b"])).resolves.toBeUndefined();
    expect(mocks.decide).toHaveBeenCalledTimes(1);
  });

  it("keeps OpenClaw's default when the bridge returns no admissible plan", async () => {
    mocks.decide.mockResolvedValueOnce({ status: "no_admissible_route" });
    await expect(invokeHook(true, ["ollama/qwen3:8b"])).resolves.toBeUndefined();
    expect(mocks.decide).toHaveBeenCalledTimes(1);
  });

  it("rejects an override when the live model row is unavailable", async () => {
    mocks.readRuntimeStatus.mockResolvedValueOnce({
      modelsCapturedAt: new Date(Date.now()).toISOString(),
      usageCapturedAt: new Date(Date.now()).toISOString(),
      models: [{ providerId: "ollama", modelId: "qwen3:8b", available: false }],
      usage: [],
    });
    await expect(invokeHook(true, ["ollama/qwen3:8b"])).resolves.toBeUndefined();
  });

  it("rejects a conflicting duplicate model catalog even when the bridge authorizes the route", async () => {
    mocks.readRuntimeStatus.mockResolvedValueOnce({
      modelsCapturedAt: new Date(Date.now()).toISOString(),
      usageCapturedAt: new Date(Date.now()).toISOString(),
      models: [
        { providerId: "ollama", modelId: "qwen3:8b", available: true },
        { providerId: "ollama", modelId: "qwen3:8b", available: false },
      ],
      usage: [],
    });
    await expect(invokeHook(true, ["ollama/qwen3:8b"])).resolves.toBeUndefined();
  });

  it("rechecks snapshot freshness after a slow bridge decision before overriding", async () => {
    mocks.decide.mockImplementationOnce(async () => {
      // The runtime catalog was fresh at request start, but became stale
      // while the bridge evaluated the route. Never trust the old snapshot.
      vi.setSystemTime(Date.now() + 61_000);
      return {
        status: "execution_plan_ready",
        providerOverride: "ollama",
        modelOverride: "qwen3:8b",
        decision_id: "decision-after-expiry",
        selected_route: { route_id: "local-route" },
      };
    });
    await expect(invokeHook(true, ["ollama/qwen3:8b"])).resolves.toBeUndefined();
    expect(mocks.decide).toHaveBeenCalledTimes(1);
  });

  it("keeps OpenClaw's default when explicit operator opt-in is absent", async () => {
    await expect(invokeHook(false)).resolves.toBeUndefined();
    expect(mocks.decide).toHaveBeenCalledTimes(1);
  });

  it("returns an override only when opt-in and the exact allowedModels entry both authorize it", async () => {
    await expect(invokeHook(true, ["ollama/qwen3:8b"])).resolves.toEqual({
      providerOverride: "ollama",
      modelOverride: "qwen3:8b",
    });
    mocks.readRuntimeStatus.mockClear();
    mocks.decide.mockClear();
    await expect(invokeHook(true, ["ollama/other-model"])).resolves.toBeUndefined();
    expect(mocks.decide).toHaveBeenCalledTimes(1);
  });
});
