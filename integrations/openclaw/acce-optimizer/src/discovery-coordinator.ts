import {
  recordModelTelemetry,
  upsertDiscoveredModel,
  type DiscoveredModel,
  type DiscoverySnapshot,
  type ModelObservation,
  type TelemetryEvidence,
} from "./discovery.js";

export type CatalogReader = {
  source: ModelObservation["source"];
  listModels(): Promise<readonly Omit<ModelObservation, "source" | "observedAt">[]>;
};

export type DiscoveryStore = {
  load(): Promise<DiscoverySnapshot>;
  save(snapshot: DiscoverySnapshot): Promise<void>;
};

export type TelemetryBootstrap = (
  model: DiscoveredModel,
) => Promise<TelemetryEvidence | undefined>;

export type DiscoveryRefreshResult = {
  discovered: number;
  added: number;
  refreshed: number;
  telemetryCaptured: number;
  telemetryPending: number;
  productionEligible: 0;
  snapshot: DiscoverySnapshot;
};

/**
 * Coordinates a user-triggered catalog refresh.
 *
 * The caller must supply a catalog reader authorized by the host/deployment.
 * This coordinator never invokes Gateway methods, runs inference, or activates
 * routes itself. Telemetry is only marked captured when the injected bootstrap
 * returns real evidence; absence/failure leaves it pending.
 */
export async function refreshModelDiscovery(params: {
  readers: readonly CatalogReader[];
  store: DiscoveryStore;
  now?: () => Date;
  bootstrapTelemetry?: TelemetryBootstrap;
}): Promise<DiscoveryRefreshResult> {
  const now = params.now ?? (() => new Date());
  const original = await params.store.load();
  let snapshot: DiscoverySnapshot = { ...original };
  let added = 0;
  let refreshed = 0;
  let telemetryCaptured = 0;

  for (const reader of params.readers) {
    const observations = await reader.listModels();
    for (const raw of observations) {
      const key = `${raw.providerId.trim().toLowerCase()}/${raw.modelId.trim()}`;
      const existed = Boolean(snapshot[key]);
      snapshot = upsertDiscoveredModel(snapshot, {
        ...raw,
        source: reader.source,
        observedAt: now().toISOString(),
      });
      if (existed) refreshed += 1;
      else added += 1;
    }
  }

  if (params.bootstrapTelemetry) {
    for (const model of Object.values(snapshot)) {
      if (model.telemetryStatus === "captured") continue;
      try {
        const evidence = await params.bootstrapTelemetry(model);
        if (evidence) {
          snapshot = recordModelTelemetry(snapshot, model.key, evidence);
          telemetryCaptured += 1;
        }
      } catch {
        // A failed measurement is not evidence. Preserve the pending state and
        // continue so one unavailable provider cannot abort the catalog refresh.
      }
    }
  }

  // Final invariant at the coordinator boundary, even if a store was seeded
  // with data produced by an older version.
  for (const model of Object.values(snapshot)) {
    if (model.productionEligible !== false) {
      throw new Error("discovery invariant violated: production eligibility must remain false");
    }
  }

  await params.store.save(snapshot);
  const models = Object.values(snapshot);
  return {
    discovered: models.length,
    added,
    refreshed,
    telemetryCaptured,
    telemetryPending: models.filter((model) => model.telemetryStatus === "pending").length,
    productionEligible: 0,
    snapshot,
  };
}

/** Small in-memory store for tests and ephemeral callers; production callers must inject durable storage. */
export function createMemoryDiscoveryStore(
  initial: DiscoverySnapshot = {},
): DiscoveryStore & { inspect(): DiscoverySnapshot } {
  let snapshot: DiscoverySnapshot = { ...initial };
  return {
    async load() {
      return { ...snapshot };
    },
    async save(next) {
      snapshot = { ...next };
    },
    inspect() {
      return { ...snapshot };
    },
  };
}
