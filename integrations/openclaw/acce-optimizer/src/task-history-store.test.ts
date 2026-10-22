import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { createTaskHistoryStore } from "./task-history-store.js";

describe("ACCE task outcome attribution", () => {
  let directory: string | undefined;
  afterEach(async () => {
    if (directory) await rm(directory, { recursive: true, force: true });
    directory = undefined;
  });

  it("records only an explicitly attributed outcome against its opaque observation id", async () => {
    directory = await mkdtemp(join(tmpdir(), "acce-task-history-"));
    const path = join(directory, "history.json");
    const store = createTaskHistoryStore(path);
    const recorded = await store.recordAndEvaluateWithId(["coding"]);
    expect(recorded.observationId).toMatch(/^[0-9a-f-]{36}$/u);
    expect(await store.recordDecision(recorded.observationId, {
      decisionId: "decision-123",
      routeId: "route-local",
      providerId: "local-provider",
      modelId: "model-a",
    })).toBe(true);
    expect(await store.recordOutcome(recorded.observationId, "success")).toBe(true);
    expect(await store.recordOutcome("missing-observation", "failure")).toBe(false);
    const history = JSON.parse(await readFile(path, "utf8")) as Array<{ observationId?: string; signature: string; outcome?: string; decisionId?: string; selectedRoute?: { routeId: string; providerId: string; modelId: string } }>;
    expect(history).toHaveLength(1);
    expect(history[0]?.signature).toBe("coding");
    expect(history[0]?.observationId).toBe(recorded.observationId);
    expect(history[0]?.outcome).toBe("success");
    expect(history[0]?.decisionId).toBe("decision-123");
    expect(history[0]?.selectedRoute).toEqual({ routeId: "route-local", providerId: "local-provider", modelId: "model-a" });
    expect(JSON.stringify(history)).not.toContain("sessionKey");
    expect(JSON.stringify(history)).not.toContain("runId");
  });

  it("preserves the existing consensus-only store API", async () => {
    directory = await mkdtemp(join(tmpdir(), "acce-task-history-"));
    const store = createTaskHistoryStore(join(directory, "history.json"));
    const result = await store.recordAndEvaluate(["coding"]);
    expect(result.eligible).toBe(false);
    expect(result.reason).toBe("insufficient_history");
  });
});
