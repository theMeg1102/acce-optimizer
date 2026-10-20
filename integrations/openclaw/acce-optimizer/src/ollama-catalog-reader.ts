import type { CatalogReader } from "./discovery-coordinator.js";

export type OllamaModelResponse = {
  models?: unknown;
};

export type OllamaFetch = (
  input: string | URL,
  init?: RequestInit,
) => Promise<Response>;

function requiredString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : undefined;
}

/**
 * Ollama /api/tags adapter. The endpoint must be explicitly configured by the
 * operator; this reader does not scan localhost, private networks, or hosts
 * discovered elsewhere. It sends no credentials and uses a bounded timeout.
 */
export function createOllamaCatalogReader(params: {
  baseUrl: string;
  fetchImpl?: OllamaFetch;
  timeoutMs?: number;
}): CatalogReader {
  const baseUrl = new URL(params.baseUrl);
  if (baseUrl.protocol !== "http:" && baseUrl.protocol !== "https:") {
    throw new TypeError("Ollama baseUrl must use http or https");
  }
  if (baseUrl.username || baseUrl.password) {
    throw new TypeError("Ollama baseUrl must not embed credentials");
  }
  if (baseUrl.search || baseUrl.hash) {
    throw new TypeError("Ollama baseUrl must not include query or fragment");
  }
  const timeoutMs = params.timeoutMs ?? 5000;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 60000) {
    throw new RangeError("timeoutMs must be an integer between 1 and 60000");
  }
  const fetchImpl = params.fetchImpl ?? fetch;
  const endpoint = new URL("api/tags", baseUrl.href.endsWith("/") ? baseUrl : `${baseUrl.href}/`);

  return {
    source: "ollama",
    async listModels() {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetchImpl(endpoint, {
          method: "GET",
          headers: { accept: "application/json" },
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Ollama catalog request failed with HTTP ${response.status}`);
        }
        const payload = await response.json() as OllamaModelResponse;
        if (!Array.isArray(payload?.models)) {
          throw new TypeError("Ollama /api/tags response must contain a models array");
        }
        const rows = new Map<string, {
          providerId: string;
          modelId: string;
          displayName?: string;
          metadata: Record<string, unknown>;
        }>();
        for (const item of payload.models) {
          if (!item || typeof item !== "object" || Array.isArray(item)) continue;
          const row = item as Record<string, unknown>;
          const modelId = requiredString(row.name) ?? requiredString(row.model);
          if (!modelId) continue;
          const metadata: Record<string, unknown> = {};
          for (const key of ["size", "digest", "modified_at"] as const) {
            const value = row[key];
            if (value === null || ["string", "number", "boolean"].includes(typeof value)) {
              metadata[key] = value;
            }
          }
          rows.set(`ollama/${modelId}`, {
            providerId: "ollama",
            modelId,
            displayName: modelId,
            metadata,
          });
        }
        return [...rows.values()];
      } finally {
        clearTimeout(timeout);
      }
    },
  };
}
