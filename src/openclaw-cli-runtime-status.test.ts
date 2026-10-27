import { describe, expect, it, vi } from "vitest";
import { readOpenClawRuntimeStatus } from "./openclaw-cli-runtime-status.js";

describe("OpenClaw read-only CLI runtime status", () => {
  it("parses only exact published model keys, positive context caps, and normalized provider quota windows", async () => {
    const runCli = vi.fn(async (_file: string, args: string[]) => ({
      stderr: "",
      stdout: args[0] === "models"
        ? JSON.stringify({ count: 2, models: [
            { key: "local-provider/local-model", available: true, contextWindow: 32768, contextTokens: 8192 },
            { key: "cloud-provider/model/with/slash", available: false, contextWindow: 64000, contextTokens: 32000 },
            { key: "bad-row", available: true },
          ] })
        : JSON.stringify({ usage: { updatedAt: 1792539466217, providers: [
            { provider: "cloud-provider", windows: [{ label: "5h", usedPercent: 39 }, { label: "Week", usedPercent: 6 }] },
            { provider: "unknown-provider", windows: [] },
            { provider: "error-provider", error: "Timeout", windows: [] },
          ] } }),
    }));
    const result = await readOpenClawRuntimeStatus({ runCli, now: () => 1792539467000 });
    expect(result.models).toEqual([
      { providerId: "local-provider", modelId: "local-model", available: true, contextWindow: 32768, contextTokens: 8192 },
      { providerId: "cloud-provider", modelId: "model/with/slash", available: false, contextWindow: 64000, contextTokens: 32000 },
    ]);
    expect(result.usage).toEqual([{ providerId: "cloud-provider", remainingFraction: 0.61 }]);
    expect(runCli).toHaveBeenCalledTimes(2);
  });

  it("keeps model availability when usage JSON is malformed, leaving cloud quota unknown", async () => {
    const runCli = vi.fn(async (_file: string, args: string[]) => ({
      stderr: "",
      stdout: args[0] === "models" ? JSON.stringify({ models: [] }) : JSON.stringify({ usage: {} }),
    }));
    const result = await readOpenClawRuntimeStatus({ runCli });
    expect(result.models).toEqual([]);
    expect(result.usage).toEqual([]);
    expect(result.usageCapturedAt).toBe("");
  });

  it("fails closed when the published model catalog JSON is malformed", async () => {
    const runCli = vi.fn(async (_file: string, args: string[]) => ({
      stderr: "",
      stdout: args[0] === "models" ? JSON.stringify({ unexpected: [] }) : JSON.stringify({ usage: { updatedAt: 1792539466217, providers: [] } }),
    }));
    await expect(readOpenClawRuntimeStatus({ runCli })).rejects.toThrow("models[]");
  });

  it("timestamps model availability before a slower usage query can make the snapshot appear newer", async () => {
    const modelReadAt = Date.parse("2026-10-27T12:00:00.000Z");
    const usageReadAt = modelReadAt + 20_000;
    let clock = modelReadAt;
    const runCli = vi.fn(async (_file: string, args: string[]) => {
      if (args[0] === "models") {
        clock = modelReadAt;
        return { stderr: "", stdout: JSON.stringify({ models: [{ key: "ollama/qwen3:8b", available: true }] }) };
      }
      clock = usageReadAt;
      return { stderr: "", stdout: JSON.stringify({ usage: { updatedAt: modelReadAt, providers: [] } }) };
    });
    const result = await readOpenClawRuntimeStatus({ runCli, now: () => clock });
    expect(result.modelsCapturedAt).toBe(new Date(modelReadAt).toISOString());
  });
});
