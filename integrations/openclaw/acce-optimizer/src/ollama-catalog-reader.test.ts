import { describe, expect, it, vi } from "vitest";
import { createOllamaCatalogReader } from "./ollama-catalog-reader.js";

function response(status: number, payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("configured Ollama catalog reader", () => {
  it("reads only the explicitly configured /api/tags endpoint and normalizes model rows", async () => {
    const fetchImpl = vi.fn(async (_input: string | URL, _init?: RequestInit) => response(200, {
      models: [
        { name: "qwen2.5:7b", size: 123, digest: "abc", modified_at: "2026-10-19T10:00:00Z" },
        { name: "qwen2.5:7b", size: 456 },
        { name: "llama3:8b", size: 789 },
        { size: 22 },
        null,
      ],
    }));
    const reader = createOllamaCatalogReader({
      baseUrl: "http://ollama.internal:11434",
      fetchImpl,
    });
    const rows = await reader.listModels();

    expect(fetchImpl).toHaveBeenCalledOnce();
    expect(String(fetchImpl.mock.calls[0][0])).toBe("http://ollama.internal:11434/api/tags");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      providerId: "ollama",
      modelId: "qwen2.5:7b",
      displayName: "qwen2.5:7b",
      metadata: { size: 456 },
    });
  });

  it("rejects invalid endpoints and embedded credentials", () => {
    expect(() => createOllamaCatalogReader({ baseUrl: "file:///etc/passwd" })).toThrow(/http or https/);
    expect(() => createOllamaCatalogReader({ baseUrl: "http://user:secret@localhost:11434" })).toThrow(/credentials/);
    expect(() => createOllamaCatalogReader({ baseUrl: "http://localhost:11434?token=x" })).toThrow(/query or fragment/);
  });

  it("rejects non-success and malformed API responses", async () => {
    const failed = createOllamaCatalogReader({
      baseUrl: "http://localhost:11434",
      fetchImpl: async () => response(503, {}),
    });
    await expect(failed.listModels()).rejects.toThrow(/HTTP 503/);

    const malformed = createOllamaCatalogReader({
      baseUrl: "http://localhost:11434",
      fetchImpl: async () => response(200, { models: "not-an-array" }),
    });
    await expect(malformed.listModels()).rejects.toThrow(/models array/);
  });

  it("aborts a timed-out request", async () => {
    const fetchImpl = vi.fn((_input: string | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    }));
    const reader = createOllamaCatalogReader({
      baseUrl: "http://localhost:11434",
      timeoutMs: 10,
      fetchImpl,
    });
    await expect(reader.listModels()).rejects.toThrow("aborted");
  });
});
