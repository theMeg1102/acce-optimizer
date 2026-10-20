import { describe, expect, it, vi } from "vitest";
import { createDecisionClient } from "./decision-client.js";

describe("ACCE decision bridge client", () => {
  it("sends a minimized decision request to the existing graph engine", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({
      status: "execution_plan_ready",
      providerOverride: "ollama",
      modelOverride: "qwen3:8b",
      engine: "authoritative",
    }), { status: 200, headers: { "content-type": "application/json" } }));
    const client = createDecisionClient({
      baseUrl: "http://127.0.0.1:18791",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const result = await client.decide({ task_class: "general", summary: "OpenClaw model selection" });
    expect(result?.providerOverride).toBe("ollama");
    expect(result?.modelOverride).toBe("qwen3:8b");
    expect(fetchImpl).toHaveBeenCalledOnce();
    const init = fetchImpl.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      request: { task_class: "general", summary: "OpenClaw model selection" },
    });
  });

  it("does not invent a route when no bridge is configured", async () => {
    const client = createDecisionClient({});
    await expect(client.decide({ task_class: "general" })).resolves.toBeUndefined();
  });

  it("rejects invalid bridge URLs", () => {
    expect(() => createDecisionClient({ baseUrl: "file:///tmp/acce" })).toThrow(/Invalid ACCE/);
  });
});
