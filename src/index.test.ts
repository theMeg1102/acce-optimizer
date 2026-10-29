import { describe, expect, it, vi } from "vitest";
import { createDecisionClient } from "./decision-client.js";

describe("ACCE adaptive decision integration", () => {
  it("does not override OpenClaw when the graph reports no admissible route", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({
      status: "alternative_state_required",
      decision_state: "no_admissible_route",
      providerOverride: null,
      modelOverride: null,
    }), { status: 200, headers: { "content-type": "application/json" } }));
    const client = createDecisionClient({
      baseUrl: "http://127.0.0.1:18791",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const result = await client.decide({
      request_id: "test",
      task_class: "general",
      summary: "OpenClaw text-generation model selection",
    });
    expect(result?.status).toBe("alternative_state_required");
    expect(result?.providerOverride).toBeNull();
    expect(result?.modelOverride).toBeNull();
  });

  it("surfaces bridge failures so the hook can fail open to OpenClaw's configured model", async () => {
    const client = createDecisionClient({
      baseUrl: "http://127.0.0.1:18791",
      fetchImpl: (async () => new Response("unavailable", { status: 503 })) as typeof fetch,
    });
    await expect(client.decide({ task_class: "general" })).rejects.toThrow(/HTTP 503/);
  });

  it("sends measured discovery evidence to the dedicated observation endpoint", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ accepted: 1 }), { status: 200 }));
    const client = createDecisionClient({
      baseUrl: "http://127.0.0.1:18791",
      bearerToken: "test-token",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    await expect(client.syncObservations({
      "ollama/qwen3:8b": { productionEligible: false, telemetryStatus: "captured" },
    })).resolves.toBe(true);
    expect(String(fetchImpl.mock.calls[0]?.[0])).toBe("http://127.0.0.1:18791/v1/observations");
    const init = fetchImpl.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer test-token");
  });
});
