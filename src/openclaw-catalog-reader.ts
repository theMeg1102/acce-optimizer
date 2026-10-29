import type { CatalogReader } from "./discovery-coordinator.js";

export type OpenClawModelRow = {
  id?: unknown;
  modelId?: unknown;
  provider?: unknown;
  providerId?: unknown;
  name?: unknown;
  label?: unknown;
  contextWindow?: unknown;
  reasoning?: unknown;
  input?: unknown;
  cost?: unknown;
  [key: string]: unknown;
};

export type ModelsListResponse = {
  models?: unknown;
};

export type AuthorizedGatewayReader = {
  /**
   * Must be supplied by an authenticated, authorized Gateway client or a
   * narrowly scoped read-only bridge. Do not wire this to an untrusted
   * plugin's runtime.gateway.request, which OpenClaw restricts by design.
   */
  listModels(params: { view: "all" | "configured" }): Promise<ModelsListResponse>;
};

function requiredString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : undefined;
}

function jsonSafeMetadata(row: OpenClawModelRow): Record<string, unknown> {
  const metadata: Record<string, unknown> = {};
  for (const key of ["contextWindow", "reasoning", "input", "cost"] as const) {
    const value = row[key];
    if (value === null || ["string", "number", "boolean"].includes(typeof value)) {
      metadata[key] = value;
    }
  }
  return metadata;
}

/**
 * Adapter for the official OpenClaw models.list result. It deliberately
 * depends on an injected authorized reader rather than obtaining credentials
 * or bypassing Gateway/plugin trust boundaries itself.
 */
export function createOpenClawCatalogReader(
  gateway: AuthorizedGatewayReader,
  view: "all" | "configured" = "all",
): CatalogReader {
  return {
    source: "openclaw",
    async listModels() {
      const response = await gateway.listModels({ view });
      if (!Array.isArray(response?.models)) {
        throw new TypeError("OpenClaw models.list response must contain a models array");
      }

      const deduplicated = new Map<string, Omit<import("./discovery.js").ModelObservation, "source" | "observedAt">>();
      for (const candidate of response.models) {
        if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
        const row = candidate as OpenClawModelRow;
        const providerId = requiredString(row.providerId) ?? requiredString(row.provider);
        const modelId = requiredString(row.id) ?? requiredString(row.modelId);
        if (!providerId || !modelId) continue;

        const observation = {
          providerId,
          modelId,
          ...(requiredString(row.name) || requiredString(row.label)
            ? { displayName: requiredString(row.name) ?? requiredString(row.label) }
            : {}),
          metadata: jsonSafeMetadata(row),
        };
        deduplicated.set(`${providerId.toLowerCase()}/${modelId}`, observation);
      }
      return [...deduplicated.values()];
    },
  };
}
