import { randomUUID } from "node:crypto";
import type { TelemetryBootstrap } from "./discovery-coordinator.js";

type FetchLike = (input: string | URL, init?: RequestInit) => Promise<Response>;

export function createOllamaTelemetryBootstrap(params: {
  baseUrl: string;
  fetchImpl?: FetchLike;
  timeoutMs?: number;
  now?: () => Date;
}): TelemetryBootstrap {
  const base = new URL(params.baseUrl);
  if (!["http:", "https:"].includes(base.protocol) ||
      base.username || base.password || base.search || base.hash) {
    throw new TypeError("Invalid Ollama telemetry base URL");
  }

  const timeoutMs = params.timeoutMs ?? 90000;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120000) {
    throw new RangeError("timeoutMs must be between 1 and 120000");
  }

  const root = new URL(base.href.endsWith("/") ? base.href : `${base.href}/`);
  const fetchImpl = params.fetchImpl ?? fetch;
  const now = params.now ?? (() => new Date());

  return async (model) => {
    // Cloud-backed models require a separate, explicit remote-probe decision.
    if (model.modelId.toLowerCase().includes("cloud")) return undefined;

    const capabilities = model.capabilities;
    const embedding = capabilities.includes("embedding");
    const completion = capabilities.includes("completion");

    // Do not guess the appropriate inference API when capabilities are unknown.
    if (embedding === completion) return undefined;

    const endpoint = new URL(embedding ? "api/embed" : "api/generate", root);
    const body = embedding
      ? { model: model.modelId, input: "ACCE telemetry probe" }
      : {
          model: model.modelId,
          prompt: "Reply with OK.",
          stream: false,
          options: { num_predict: 1 },
        };

    const started = Date.now();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetchImpl(endpoint, {
        method: "POST",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`Ollama telemetry probe failed with HTTP ${response.status}`);
      }

      const payload: unknown = await response.json();
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
        throw new TypeError("Ollama telemetry response must be a JSON object");
      }

      const result = payload as Record<string, unknown>;

  if (!embedding && typeof result.response !== "string") {
    throw new TypeError(
      "Ollama generation response must contain a string response",
    );
  }
      const latencyMs = Date.now() - started;
      const metrics: Record<string, number | string | boolean | null> = {
        available: true,
        latencyMs,
        probeType: embedding ? "embedding" : "generation",
        endpoint: embedding ? "/api/embed" : "/api/generate",
      };

      if (embedding) {
        const vectors = result.embeddings;
        if (!Array.isArray(vectors) ||
            !Array.isArray(vectors[0]) ||
            vectors[0].length === 0 ||
            !vectors[0].every((n) => typeof n === "number" && Number.isFinite(n))) {
          throw new TypeError("Ollama returned no valid embedding vector");
        }
        metrics.embeddingDimensions = vectors[0].length;
      } else {
        // Persist counts and timings only, never the generated response text.
        for (const key of [
          "total_duration",
          "load_duration",
          "prompt_eval_count",
          "prompt_eval_duration",
          "eval_count",
          "eval_duration",
        ]) {
          const value = result[key];
          if (typeof value === "number" && Number.isFinite(value)) {
            metrics[key] = value;
          }
        }
      }

      const capturedAt = now().toISOString();
      return {
        capturedAt,
        measurementId: `ollama-probe-${randomUUID()}`,
        metrics,
      };
    } finally {
      clearTimeout(timeout);
    }
  };
}
