/**
 * Governed model-discovery primitives for the OpenClaw adapter.
 *
 * This module deliberately does not call the Gateway or enable routes. A
 * separately authorized catalog reader supplies normalized observations.
 * Discovery is inventory, never production-eligibility evidence.
 */

export type DiscoverySource = "openclaw" | "ollama" | "configured" | "custom";

export type ModelObservation = {
  providerId: string;
  modelId: string;
  source: DiscoverySource;
  observedAt: string;
  displayName?: string;
  capabilities?: readonly string[];
  metadata?: Readonly<Record<string, unknown>>;
};

export type TelemetryEvidence = {
  capturedAt: string;
  measurementId: string;
  metrics: Readonly<Record<string, number | string | boolean | null>>;
};

export type DiscoveredModel = {
  key: string;
  providerId: string;
  modelId: string;
  displayName: string;
  sources: readonly DiscoverySource[];
  capabilities: readonly string[];
  metadata: Readonly<Record<string, unknown>>;
  firstSeenAt: string;
  lastSeenAt: string;
  telemetryStatus: "pending" | "captured";
  telemetry?: TelemetryEvidence;
  userAdded: boolean;
  lifecycle: "DISCOVERED" | "TELEMETRY_PENDING" | "TELEMETRY_CAPTURED" | "USER_ADDED";
  productionEligible: false;
};

export type DiscoverySnapshot = Readonly<Record<string, DiscoveredModel>>;

function nonEmpty(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new TypeError(`${field} must be a non-empty string`);
  }
  return value.trim();
}

function validateTimestamp(value: string, field: string): string {
  const timestamp = nonEmpty(value, field);
  if (!Number.isFinite(Date.parse(timestamp))) {
    throw new TypeError(`${field} must be a valid timestamp`);
  }
  return timestamp;
}

export function modelKey(providerId: string, modelId: string): string {
  return `${nonEmpty(providerId, "providerId").toLowerCase()}/${nonEmpty(modelId, "modelId")}`;
}

/**
 * Merge a fresh catalog observation into an inventory snapshot.
 * Existing telemetry and explicit user intent survive repeated discovery.
 */
export function upsertDiscoveredModel(
  snapshot: DiscoverySnapshot,
  observation: ModelObservation,
): DiscoverySnapshot {
  const providerId = nonEmpty(observation.providerId, "providerId");
  const modelId = nonEmpty(observation.modelId, "modelId");
  const observedAt = validateTimestamp(observation.observedAt, "observedAt");
  const key = modelKey(providerId, modelId);
  const previous = snapshot[key];
  const source = observation.source;

  const sources = [...new Set([...(previous?.sources ?? []), source])].sort();
  const capabilities = [...new Set([
    ...(previous?.capabilities ?? []),
    ...(observation.capabilities ?? []),
  ])].sort();
  const telemetryStatus = previous?.telemetryStatus ?? "pending";
  const userAdded = previous?.userAdded ?? false;
  const lifecycle = userAdded
    ? "USER_ADDED"
    : telemetryStatus === "captured"
      ? "TELEMETRY_CAPTURED"
      : previous
        ? "TELEMETRY_PENDING"
        : "DISCOVERED";

  const next: DiscoveredModel = {
    key,
    providerId,
    modelId,
    displayName: observation.displayName?.trim() || previous?.displayName || modelId,
    sources,
    capabilities,
    metadata: { ...(previous?.metadata ?? {}), ...(observation.metadata ?? {}) },
    firstSeenAt: previous?.firstSeenAt ?? observedAt,
    lastSeenAt: observedAt,
    telemetryStatus,
    ...(previous?.telemetry ? { telemetry: previous.telemetry } : {}),
    userAdded,
    lifecycle,
    productionEligible: false,
  };
  return { ...snapshot, [key]: next };
}

/** Record telemetry without granting route candidacy or production eligibility. */
export function recordModelTelemetry(
  snapshot: DiscoverySnapshot,
  key: string,
  evidence: TelemetryEvidence,
): DiscoverySnapshot {
  const current = snapshot[key];
  if (!current) throw new RangeError(`unknown discovered model: ${key}`);
  const capturedAt = validateTimestamp(evidence.capturedAt, "capturedAt");
  const measurementId = nonEmpty(evidence.measurementId, "measurementId");
  const metrics = { ...evidence.metrics };
  for (const [name, value] of Object.entries(metrics)) {
    if (!name.trim()) throw new TypeError("telemetry metric names must be non-empty");
    if (typeof value === "number" && !Number.isFinite(value)) {
      throw new TypeError(`telemetry metric ${name} must be finite`);
    }
  }
  return {
    ...snapshot,
    [key]: {
      ...current,
      telemetryStatus: "captured",
      telemetry: { capturedAt, measurementId, metrics },
      lifecycle: current.userAdded ? "USER_ADDED" : "TELEMETRY_CAPTURED",
      productionEligible: false,
    },
  };
}

/** Only an explicit user action can mark a discovered model as user-added. */
export function markModelUserAdded(
  snapshot: DiscoverySnapshot,
  key: string,
): DiscoverySnapshot {
  const current = snapshot[key];
  if (!current) throw new RangeError(`unknown discovered model: ${key}`);
  return {
    ...snapshot,
    [key]: {
      ...current,
      userAdded: true,
      lifecycle: "USER_ADDED",
      productionEligible: false,
    },
  };
}
