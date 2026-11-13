import { describe, expect, it, vi } from "vitest";
import { createOpenClawCatalogReader } from "./openclaw-catalog-reader.js";

describe("OpenClaw models.list catalog reader", () => {
  it("maps and deduplicates catalog rows while keeping only safe metadata fields", async () => {
    const listModels = vi.fn(async () => ({
      models: [
        { provider: "OpenAI", id: "gpt-a", name: "GPT A", contextWindow: 128000, reasoning: true },
        { provider: "OpenAI", id: "gpt-a", name: "GPT A renamed", contextWindow: 256000 },
        { providerId: "ollama", modelId: "qwen-local", label: "Qwen", cost: { input: 0 } },
        { provider: "missing-id" },
        null,
        "invalid",
      ],
    }));
    const reader = createOpenClawCatalogReader({ listModels }, "configured");
    const rows = await reader.listModels();

    expect(listModels).toHaveBeenCalledWith({ view: "configured" });
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      providerId: "OpenAI",
      modelId: "gpt-a",
      displayName: "GPT A renamed",
      metadata: { contextWindow: 256000 },
    });
    expect(rows[1]).toMatchObject({
      providerId: "ollama",
      modelId: "qwen-local",
      displayName: "Qwen",
      metadata: {},
    });
  });

  it("rejects malformed catalog responses rather than silently claiming an empty catalog", async () => {
    const reader = createOpenClawCatalogReader({
      async listModels() {
        return { models: { bad: "shape" } };
      },
    });
    await expect(reader.listModels()).rejects.toThrow(/models array/);
  });

  it("propagates authorization and transport failures from the supplied reader", async () => {
    const reader = createOpenClawCatalogReader({
      async listModels() {
        throw new Error("forbidden");
      },
    });
    await expect(reader.listModels()).rejects.toThrow("forbidden");
  });
});
