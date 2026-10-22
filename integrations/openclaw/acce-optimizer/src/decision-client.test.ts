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

  it("sends runtime catalog and explicit preference outside the normalized request envelope", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ status: "alternative_state_required" }), { status: 200 }));
    const client = createDecisionClient({ baseUrl: "http://127.0.0.1:18791", fetchImpl: fetchImpl as unknown as typeof fetch });
    await client.decide({
      request_id: "envelope-test",
      summary: "coding task",
      runtime_catalog: [{ providerId: "local", modelId: "model-a" }],
      preference: { providerId: "local", modelId: "model-a" },
      task_signature: "coding|programming",
    });
    const init = fetchImpl.mock.calls[0]?.[1] as RequestInit;
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.runtime_catalog).toEqual([{ providerId: "local", modelId: "model-a" }]);
    expect(body.preference).toEqual({ providerId: "local", modelId: "model-a" });
    expect(body.task_signature).toBe("coding|programming");
    expect(body.request).not.toHaveProperty("runtime_catalog");
    expect(body.request).not.toHaveProperty("preference");
    expect(body.request).not.toHaveProperty("task_signature");
  });

  it("sends attributed run outcomes to the dedicated endpoint", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ accepted: 1 }), { status: 200 }));
    const client = createDecisionClient({ baseUrl: "http://127.0.0.1:18791", fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(client.recordOutcome({ route_id: "route-a", outcome: "success" })).resolves.toBe(true);
    expect(String(fetchImpl.mock.calls[0]?.[0])).toBe("http://127.0.0.1:18791/v1/outcomes");
  });

  it("does not invent a route when no bridge is configured", async () => {
    const client = createDecisionClient({});
    await expect(client.decide({ task_class: "general" })).resolves.toBeUndefined();
  });

  it("rejects invalid bridge URLs", () => {
    expect(() => createDecisionClient({ baseUrl: "file:///tmp/acce" })).toThrow(/Invalid ACCE/);
  });
});
