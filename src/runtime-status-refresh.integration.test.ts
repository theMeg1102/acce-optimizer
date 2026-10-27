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
vi.mock("./openclaw-override-policy.js", () => ({
  isModelOverrideAllowed: () => true,
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

describe("ACCE runtime status refresh failure", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.readRuntimeStatus.mockReset();
    mocks.decide.mockReset();
    mocks.recordAndEvaluateWithId.mockReset().mockResolvedValue({
      observationId: "observation-test",
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
    mocks.decide.mockResolvedValue({
      status: "execution_plan_ready",
      providerOverride: "ollama",
      modelOverride: "qwen3:8b",
      decision_id: "decision-test",
      selected_route: { route_id: "local-route" },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("invalidates a previously successful snapshot after a later refresh fails and refuses an override", async () => {
    mocks.readRuntimeStatus
      .mockResolvedValueOnce({
        modelsCapturedAt: new Date(Date.now()).toISOString(),
        usageCapturedAt: "",
        models: [{ providerId: "ollama", modelId: "qwen3:8b", available: true }],
        usage: [],
      })
      .mockRejectedValueOnce(new Error("CLI unavailable"));

    const hooks = new Map<string, (...args: any[]) => unknown>();
    const services: Array<{ id: string; start: () => void; stop?: () => void }> = [];
    const api = {
      pluginConfig: {
        mode: "adaptive",
        decisionServiceUrl: "http://127.0.0.1:18791",
        similarityHistoryPath: "/tmp/acce-runtime-status-policy-test.json",
        runtimeStatusRefreshSeconds: 60,
      },
      config: { plugins: { entries: { "acce-optimizer": { llm: { allowModelOverride: true } } } } },
      registrationMode: "full",
      logger: { info: vi.fn(), warn: vi.fn() },
      on: (event: string, handler: (...args: any[]) => unknown) => hooks.set(event, handler),
      registerService: (service: { id: string; start: () => void; stop?: () => void }) => services.push(service),
      registerCli: vi.fn(),
    };

    (plugin as unknown as { setup: (api: typeof api) => void }).setup(api);
    const runtimeService = services.find((service) => service.id === "acce-optimizer-runtime-status");
    expect(runtimeService).toBeDefined();
    runtimeService?.start();

    await vi.advanceTimersByTimeAsync(15_000);
    expect(mocks.readRuntimeStatus).toHaveBeenCalledTimes(1);

    // The scheduled refresh fails. The previous snapshot must be discarded.
    await vi.advanceTimersByTimeAsync(45_000);
    expect(mocks.readRuntimeStatus).toHaveBeenCalledTimes(2);

    const hook = hooks.get("before_model_resolve");
    expect(hook).toBeDefined();
    const result = await hook?.({ prompt: "write a short summary" }, {});
    expect(result).toBeUndefined();
    expect(mocks.decide).not.toHaveBeenCalled();

    runtimeService?.stop?.();
  });
});
