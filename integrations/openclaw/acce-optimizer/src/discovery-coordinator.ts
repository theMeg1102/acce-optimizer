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

export type DiscoveryProgressEvent =
  | { type: "catalog_started"; source: string; index: number; total: number }
  | { type: "catalog_completed"; source: string; index: number; total: number; models: number }
  | { type: "catalog_failed"; source: string; index: number; total: number; error: string }
  | { type: "telemetry_started"; modelKey: string; modelId: string; index: number; total: number }
  | { type: "telemetry_completed"; modelKey: string; modelId: string; index: number; total: number; captured: boolean }
  | { type: "telemetry_failed"; modelKey: string; modelId: string; index: number; total: number; error: string }
  | {
      type: "refresh_completed";
      discovered: number;
      added: number;
      refreshed: number;
      telemetryCaptured: number;
      telemetryPending: number;
      productionEligible: 0;
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
  onProgress?: (event: DiscoveryProgressEvent) => void;
}): Promise<DiscoveryRefreshResult> {
  const now = params.now ?? (() => new Date());
  const original = await params.store.load();
  let snapshot: DiscoverySnapshot = { ...original };
  let added = 0;
  let refreshed = 0;
  let telemetryCaptured = 0;

  // Progress reporting is observational: logger/callback errors must never
  // change discovery, telemetry, persistence, or production eligibility.
  const emit = (event: DiscoveryProgressEvent): void => {
    try {
      params.onProgress?.(event);
    } catch {
      // Ignore observer failures.
    }
  };

  for (const [readerOffset, reader] of params.readers.entries()) {
    const readerIndex = readerOffset + 1;
    emit({
      type: "catalog_started",
      source: reader.source,
      index: readerIndex,
      total: params.readers.length,
    });

    let observations: Awaited<ReturnType<CatalogReader["listModels"]>>;
    try {
      observations = await reader.listModels();
    } catch (error) {
      emit({
        type: "catalog_failed",
        source: reader.source,
        index: readerIndex,
        total: params.readers.length,
        error: error instanceof Error ? error.message : String(error),
      });
      throw error;
    }

    emit({
      type: "catalog_completed",
      source: reader.source,
      index: readerIndex,
      total: params.readers.length,
      models: observations.length,
    });
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
    const telemetryModels = Object.values(snapshot).filter(
      (model) => model.telemetryStatus !== "captured",
    );
    for (const [offset, model] of telemetryModels.entries()) {
      const index = offset + 1;
      const total = telemetryModels.length;
      emit({
        type: "telemetry_started",
        modelKey: model.key,
        modelId: model.modelId,
        index,
        total,
      });
      try {
        const evidence = await params.bootstrapTelemetry(model);
        if (evidence) {
          snapshot = recordModelTelemetry(snapshot, model.key, evidence);
          telemetryCaptured += 1;
        }
        emit({
          type: "telemetry_completed",
          modelKey: model.key,
          modelId: model.modelId,
          index,
          total,
          captured: Boolean(evidence),
        });
      } catch (error) {
        emit({
          type: "telemetry_failed",
          modelKey: model.key,
          modelId: model.modelId,
          index,
          total,
          error: error instanceof Error ? error.message : String(error),
        });
        // Failed measurement is not evidence. Keep pending and continue.
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
  const result: DiscoveryRefreshResult = {
    discovered: models.length,
    added,
    refreshed,
    telemetryCaptured,
    telemetryPending: models.filter((model) => model.telemetryStatus === "pending").length,
    productionEligible: 0,
    snapshot,
  };
  emit({
    type: "refresh_completed",
    discovered: result.discovered,
    added: result.added,
    refreshed: result.refreshed,
    telemetryCaptured: result.telemetryCaptured,
    telemetryPending: result.telemetryPending,
    productionEligible: result.productionEligible,
  });
  return result;
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
