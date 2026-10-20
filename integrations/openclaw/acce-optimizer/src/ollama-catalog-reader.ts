import type { CatalogReader } from "./discovery-coordinator.js";

export type OllamaModelResponse = {
  models?: unknown;
};

export type OllamaFetch = (
  input: string | URL,
  init?: RequestInit,
) => Promise<Response>;

function requiredString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : undefined;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(
    value
      .filter((item): item is string =>
        typeof item === "string" && item.trim().length > 0)
      .map((item) => item.trim()),
  )].sort();
}

function scalarMetadata(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    if (item === null || ["string", "number", "boolean"].includes(typeof item)) {
      result[key] = item;
    }
  }
  return result;
}

/**
 * Reads an explicitly configured Ollama catalog and enriches each unique
 * model using /api/show. A failed enrichment never grants production access.
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
  const root = new URL(baseUrl.href.endsWith("/") ? baseUrl.href : `${baseUrl.href}/`);
  const tagsEndpoint = new URL("api/tags", root);
  const showEndpoint = new URL("api/show", root);

  async function requestJson(
    endpoint: URL,
    init: RequestInit,
    label: string,
  ): Promise<unknown> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(endpoint, {
        ...init,
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`Ollama ${label} request failed with HTTP ${response.status}`);
      }
      return await response.json() as unknown;
    } finally {
      clearTimeout(timeout);
    }
  }

  return {
    source: "ollama",
    async listModels() {
      const payload = await requestJson(tagsEndpoint, {
        method: "GET",
        headers: { accept: "application/json" },
      }, "catalog") as OllamaModelResponse;

      if (!Array.isArray(payload?.models)) {
        throw new TypeError("Ollama /api/tags response must contain a models array");
      }

      const rows = new Map<string, {
        providerId: string;
        modelId: string;
        displayName: string;
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

      const observations = [];
      for (const row of rows.values()) {
        let capabilities: string[] = [];
        let capabilityStatus: "captured" | "unavailable" = "unavailable";
        let metadata = row.metadata;

        try {
          const show = await requestJson(showEndpoint, {
            method: "POST",
            headers: {
              accept: "application/json",
              "content-type": "application/json",
            },
            body: JSON.stringify({ model: row.modelId, verbose: false }),
          }, "model details") as Record<string, unknown>;

          capabilities = stringArray(show?.capabilities);
          capabilityStatus = "captured";
          const details = scalarMetadata(show?.details);
          metadata = {
            ...metadata,
            ...(Object.keys(details).length > 0 ? { details } : {}),
          };
        } catch {
          // Keep the model discovered; failed enrichment is not evidence.
        }

        observations.push({
          ...row,
          capabilities,
          metadata: { ...metadata, capabilityStatus },
        });
      }

      return observations;
    },
  };
}
