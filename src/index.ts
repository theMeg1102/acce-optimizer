import { randomUUID } from "node:crypto";
import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { defineFeaturePlugin } from "openclaw/plugin-sdk/feature-plugin";
import { createJsonFileDiscoveryStore } from "./json-file-discovery-store.js";
import { refreshModelDiscovery, type DiscoveryRefreshResult } from "./discovery-coordinator.js";
import { shouldRunInitialDiscovery } from "./autodiscovery-policy.js";
import { contract } from "./contract.js";
import { createOllamaCatalogReader } from "./ollama-catalog-reader.js";
import { createOllamaTelemetryBootstrap } from "./ollama-telemetry.js";
import { createDecisionClient } from "./decision-client.js";
import { deriveTaskProfile } from "./task-profile.js";
import { createTaskHistoryStore } from "./task-history-store.js";
import { evaluateSimilarityWindow } from "./task-similarity.js";
import { readConfiguredRuntimeModels, sanitizeModelTelemetry } from "./openclaw-runtime-state.js";
import { isModelOverrideAllowed } from "./openclaw-override-policy.js";
import { readOpenClawRuntimeStatus, type OpenClawRuntimeStatus } from "./openclaw-cli-runtime-status.js";
import { isKnownLocalProvider, isRuntimeStatusFresh, runtimeOverrideBlockReason } from "./runtime-status-policy.js";

type AccePluginConfig = {
  enabled?: boolean;
  mode?: "shadow" | "adaptive";
  decisionServiceUrl?: string;
  decisionServiceToken?: string;
  allowExternalNetwork?: boolean;
  maxCloudCostUsd?: number;
  autoDiscoverOnStartup?: boolean;
  ollamaUrl?: string;
  inventoryPath?: string;
  similarityHistoryPath?: string;
  similarityThreshold?: number;
  preferredRoutes?: Partial<Record<"coding" | "research" | "analysis" | "general", { providerId: string; modelId: string }>>;
  openclawCliPath?: string;
  runtimeStatusRefreshSeconds?: number;
};

function isEnabled(config: AccePluginConfig): boolean {
  // OpenClaw controls whether this plugin is loaded via plugins.entries.<id>.enabled.
  // api.pluginConfig contains only the plugin-specific config object, so `enabled`
  // is an optional plugin-level kill switch rather than a mirror of host enablement.
  return config.enabled !== false && (config.mode === undefined || config.mode === "shadow" || config.mode === "adaptive");
}

function configuredOllamaUrl(config: AccePluginConfig): string {
  return config.ollamaUrl?.trim() || process.env.ACCE_OLLAMA_URL?.trim() || "http://127.0.0.1:11434";
}

function resolveStorePath(rawPath: string): string {
  const expanded = rawPath.startsWith("~/") ? join(homedir(), rawPath.slice(2)) : rawPath;
  if (!isAbsolute(expanded)) {
    throw new TypeError("discovery inventory path must be absolute or start with ~/");
  }
  return resolve(expanded);
}

function safeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default defineFeaturePlugin({
  contract,
  name: "ACCE Optimizer",
  description:
    "Governed adaptive model routing, cost optimization, quota preservation, and context-aware execution planning for OpenClaw.",
  setup(api) {
    const config = (api.pluginConfig ?? {}) as AccePluginConfig;
    const taskHistory = createTaskHistoryStore(resolveStorePath(config.similarityHistoryPath ?? "~/.openclaw/acce-optimizer-data/task-history.json"));
    // Correlation ids are transient in-memory only; persistent history stores a random observation id, never a run/session id.
    const runObservations = new Map<string, { observationId: string; taskSignature: string; decisionId?: string; routeId?: string; providerId?: string; modelId?: string }>();
    let runtimeStatus: OpenClawRuntimeStatus | undefined;
    let runtimeStatusRefreshTimer: ReturnType<typeof setInterval> | undefined;
    let runtimeStatusStartupTimer: ReturnType<typeof setTimeout> | undefined;
    let runtimeStatusRefreshInProgress = false;
    let runtimeStatusAbortController: AbortController | undefined;
    const requestedRuntimeRefreshSeconds = Number.isFinite(config.runtimeStatusRefreshSeconds) ? Math.floor(config.runtimeStatusRefreshSeconds as number) : 300;
    const runtimeStatusRefreshIntervalSeconds = Math.max(60, Math.min(900, requestedRuntimeRefreshSeconds));
    const runtimeStatusMaxAgeMs = runtimeStatusRefreshIntervalSeconds * 1000;
    const refreshRuntimeStatus = async (): Promise<void> => {
      if (runtimeStatusRefreshInProgress) return;
      runtimeStatusRefreshInProgress = true;
      try {
        runtimeStatusAbortController = new AbortController();
        const snapshot = await readOpenClawRuntimeStatus({ cliPath: config.openclawCliPath, timeoutMs: 18_000, signal: runtimeStatusAbortController.signal });
        runtimeStatus = snapshot;
        api.logger.info(JSON.stringify({ event: "acce.runtime_status.refreshed", models: snapshot.models.length, providersWithUsage: snapshot.usage.length, usageFresh: Boolean(snapshot.usageCapturedAt) }));
      } catch (error) {
        // A failed refresh invalidates the prior snapshot; it must never authorize a later override.
        runtimeStatus = undefined;
        if (!runtimeStatusAbortController?.signal.aborted) api.logger.warn(JSON.stringify({ event: "acce.runtime_status.refresh_failed", error: safeError(error), action: "fail_closed_for_model_override_until_refresh" }));
      } finally {
        runtimeStatusAbortController = undefined;
        runtimeStatusRefreshInProgress = false;
      }
    };
    const runtimeModels = readConfiguredRuntimeModels(api.config);
    api.logger.info(JSON.stringify({ event: "acce.runtime.catalog_observed", source: "openclaw-effective-config", modelCount: runtimeModels.length, pricedModelCount: runtimeModels.filter((model) => model.cost !== undefined).length }));

    const decisionClient = createDecisionClient({
      baseUrl: config.decisionServiceUrl ?? process.env.ACCE_DECISION_SERVICE_URL,
      bearerToken: config.decisionServiceToken ?? process.env.ACCE_DECISION_TOKEN,
    });

    api.on("before_model_resolve", async (event, ctx) => {
      if (!isEnabled(config)) return;
      const mode = config.mode ?? "adaptive";
      // Build and persist only category signatures, even in shadow mode, so
      // operators can accumulate history without allowing model overrides.
      const taskProfile = deriveTaskProfile(event.prompt);
      let patternConsensus = evaluateSimilarityWindow(taskProfile.categories, [], { threshold: config.similarityThreshold ?? 0.8 });
      let learnedRouteOrder: string[] | undefined;
      try {
        const recorded = await taskHistory.recordAndEvaluateWithId(taskProfile.categories, config.similarityThreshold ?? 0.8);
        patternConsensus = recorded.consensus;
        if (patternConsensus.eligible) learnedRouteOrder = await taskHistory.getSuccessfulTemplate(taskProfile.categories);
        if (typeof ctx.runId === "string" && ctx.runId.length > 0) {
          runObservations.set(ctx.runId, { observationId: recorded.observationId, taskSignature: taskProfile.categories.slice().sort().join("|") });
          while (runObservations.size > 1000) {
            const oldest = runObservations.keys().next().value;
            if (typeof oldest !== "string") break;
            runObservations.delete(oldest);
          }
        }
      } catch (error) {
        api.logger.warn(JSON.stringify({ event: "acce.similarity.history_unavailable", error: safeError(error), action: "use_per_task_decision" }));
      }
      api.logger.info(JSON.stringify({ event: "acce.similarity.consensus", eligibleForDefaultPattern: patternConsensus.eligible, sampleSize: patternConsensus.sampleSize, matchingCount: patternConsensus.matchingCount, matchingFraction: patternConsensus.matchingFraction, requiredMatches: patternConsensus.requiredMatches, windowSizesEvaluated: patternConsensus.windowSizesEvaluated, reason: patternConsensus.reason }));
      if (mode === "shadow") {
        api.logger.info(JSON.stringify({
          event: "acce.decision.shadow_observation",
          hook: "before_model_resolve",
          promptPresent: typeof event.prompt === "string" && event.prompt.length > 0,
          eligibleForDefaultPattern: patternConsensus.eligible,
        }));
        return;
      }
      if (!decisionClient.configured) {
        api.logger.warn(JSON.stringify({
          event: "acce.decision.unavailable",
          reason: "decision-service-not-configured",
          action: "keeping-openclaw-default-model",
        }));
        return;
      }

      // Do not ask the bridge to select a route unless the local runtime snapshot is fresh.
      const decisionRuntimeStatus = runtimeStatus;
      if (!isRuntimeStatusFresh(decisionRuntimeStatus, Date.now(), runtimeStatusMaxAgeMs)) {
        api.logger.warn(JSON.stringify({ event: "acce.decision.runtime_status_unavailable", action: "keeping-openclaw-default-model" }));
        return;
      }

      // Never send prompt, attachments, history, or session identifiers to the bridge.
      try {
        const decision = await decisionClient.decide({
          request_id: `openclaw-${randomUUID()}`,
          // Send allowlisted catalog metadata only: ACCE intersects this live configured catalog
          // with its operator-authorized registry before graph construction.
          runtime_catalog: runtimeModels.map((model) => ({ providerId: model.providerId, modelId: model.modelId, ...(model.contextWindow ? { contextWindow: model.contextWindow } : {}), ...(model.contextTokens ? { contextTokens: model.contextTokens } : {}), ...(model.maxTokens ? { maxTokens: model.maxTokens } : {}), ...(model.cost ? { cost: model.cost } : {}) })),
          task_signature: taskProfile.categories.slice().sort().join("|"),
          runtime_status_required: true,
          runtime_status: decisionRuntimeStatus ?? null,
          ...(learnedRouteOrder ? { preferred_route_order: learnedRouteOrder } : {}),
          ...(config.preferredRoutes?.[taskProfile.taskClass] ? { preference: config.preferredRoutes[taskProfile.taskClass] } : {}),
          task_class: taskProfile.taskClass,
          summary: `${taskProfile.summary}; historical_pattern=${patternConsensus.eligible ? "eligible" : "not-established"}; matching_fraction=${patternConsensus.matchingFraction.toFixed(4)}`,
          required_capabilities: ["text-generation"],
          profile: "balanced_local_first",
          constraints: {
            privacy_level: "unknown",
            external_network_allowed: config.allowExternalNetwork === true,
            max_cloud_cost_usd: config.maxCloudCostUsd ?? 0,
            max_latency_ms: 120000,
            min_quality_score: 0,
            search_budget: { max_candidate_routes: 100 },
            quota_budget: { remaining_fraction: 1 },
          },
          urgency: taskProfile.urgency,
          governance: { validation_required: true },
        });
        if (decision?.status !== "execution_plan_ready" ||
            !decision.providerOverride || !decision.modelOverride) {
          api.logger.info(JSON.stringify({
            event: "acce.decision.no_override",
            decisionId: decision?.decision_id ?? null,
            decisionState: decision?.decision_state ?? null,
          }));
          return;
        }
        // Never let a stale ACCE registry select a model absent from the
        // effective OpenClaw catalog. Empty/unreadable catalog means fail open.
        if (runtimeModels.length === 0 || !runtimeModels.some((model) =>
          model.providerId === decision.providerOverride && model.modelId === decision.modelOverride
        )) {
          api.logger.warn(JSON.stringify({
            event: "acce.decision.runtime_catalog_mismatch",
            provider: decision.providerOverride,
            model: decision.modelOverride,
            runtimeCatalogCount: runtimeModels.length,
            action: "keeping-openclaw-default-model",
          }));
          return;
        }
        if (!isModelOverrideAllowed(api.config, contract.pluginId, decision.providerOverride, decision.modelOverride)) {
          api.logger.warn(JSON.stringify({
            event: "acce.decision.override_not_authorized",
            provider: decision.providerOverride,
            model: decision.modelOverride,
            action: "keeping-openclaw-default-model",
          }));
          return;
        }
        if (config.allowExternalNetwork !== true && !isKnownLocalProvider(decision.providerOverride)) {
          api.logger.warn(JSON.stringify({
            event: "acce.decision.external_route_rejected",
            provider: decision.providerOverride,
            model: decision.modelOverride,
            action: "keeping-openclaw-default-model",
          }));
          return;
        }
        const runtimeBlockReason = runtimeOverrideBlockReason(runtimeStatus, decision.providerOverride, decision.modelOverride, {
          now: Date.now(),
          maxAgeMs: runtimeStatusMaxAgeMs,
          // When external routes are enabled, do not select a remote provider without fresh, non-exhausted usage telemetry.
          requireFreshProviderUsage: config.allowExternalNetwork === true && !isKnownLocalProvider(decision.providerOverride),
        });
        if (runtimeBlockReason) {
          api.logger.warn(JSON.stringify({
            event: "acce.decision.runtime_eligibility_rejected",
            provider: decision.providerOverride,
            model: decision.modelOverride,
            reason: runtimeBlockReason,
            action: "keeping-openclaw-default-model",
          }));
          return;
        }
        const selectedRoute = decision.selected_route;
        if (typeof ctx.runId === "string" && ctx.runId.length > 0 && typeof decision.decision_id === "string" && selectedRoute?.route_id) {
          const observation = runObservations.get(ctx.runId);
          if (observation) {
            observation.decisionId = typeof decision.decision_id === "string" ? decision.decision_id : undefined;
            observation.routeId = selectedRoute.route_id;
            observation.providerId = decision.providerOverride;
            observation.modelId = decision.modelOverride;
            void taskHistory.recordDecision(observation.observationId, {
              decisionId: decision.decision_id,
              routeId: selectedRoute.route_id,
              providerId: decision.providerOverride,
              modelId: decision.modelOverride,
              rankedRoutes: (decision.ranking_result ?? []).map((item) => item.route_id).filter((routeId): routeId is string => typeof routeId === "string"),
            }).then((recorded) => {
              if (!recorded) api.logger.warn(JSON.stringify({ event: "acce.learning.route_attribution_missing", action: "keep_observation_unattributed" }));
            }).catch((error: unknown) => api.logger.warn(JSON.stringify({ event: "acce.learning.route_attribution_failed", error: safeError(error) })));
          }
        }
        api.logger.info(JSON.stringify({
          event: "acce.decision.route_selected",
          decisionId: decision.decision_id ?? null,
          routeId: decision.selected_route?.route_id ?? null,
          provider: decision.providerOverride,
          model: decision.modelOverride,
          engine: decision.engine ?? "adaptive_graph",
          policyMode: decision.policy_mode ?? "unknown",
        }));
        return {
          providerOverride: decision.providerOverride,
          modelOverride: decision.modelOverride,
        };
      } catch (error) {
        api.logger.warn(JSON.stringify({
          event: "acce.decision.failed",
          error: safeError(error),
          action: "keeping-openclaw-default-model",
        }));
        return;
      }
    });

    // Attribute only the host's explicit run success/failure to the matching
    // transient run observation. Do not infer preference from model-call telemetry.
    api.on("agent_end", (event, ctx) => {
      const runId = typeof event.runId === "string" ? event.runId : typeof ctx.runId === "string" ? ctx.runId : undefined;
      if (!runId) return;
      const observation = runObservations.get(runId);
      if (!observation) return;
      runObservations.delete(runId);
      const outcome = typeof event.success === "boolean" ? (event.success ? "success" : "failure") : undefined;
      if (!outcome) return;
      void taskHistory.recordOutcome(observation.observationId, outcome).then((updated) => {
        api.logger.info(JSON.stringify({ event: "acce.learning.outcome_recorded", attributed: updated, outcome }));
      }).catch((error: unknown) => api.logger.warn(JSON.stringify({ event: "acce.learning.outcome_unavailable", error: safeError(error) })));
      if (decisionClient.configured && observation.decisionId && observation.routeId && observation.providerId && observation.modelId) {
        void decisionClient.recordOutcome({
          route_id: observation.routeId,
          provider_id: observation.providerId,
          model_id: observation.modelId,
          task_signature: observation.taskSignature,
          outcome,
          ...(observation.decisionId ? { decision_id: observation.decisionId } : {}),
        }).then((accepted) => {
          api.logger.info(JSON.stringify({ event: "acce.learning.route_outcome_synced", accepted, outcome }));
        }).catch((error: unknown) => api.logger.warn(JSON.stringify({ event: "acce.learning.route_outcome_sync_failed", error: safeError(error) })));
      }
    });

    // Native OpenClaw 2026.10.5 typed telemetry hooks; aggregate fields only.
    api.on("model_call_started", (event) => {
      const telemetry = sanitizeModelTelemetry(event);
      api.logger.info(JSON.stringify({ event: "acce.telemetry.model_call_started", ...telemetry }));
    });
    api.on("model_call_ended", (event) => {
      const telemetry = sanitizeModelTelemetry(event);
      api.logger.info(JSON.stringify({ event: "acce.telemetry.model_call_ended", ...telemetry }));
      if (!decisionClient.configured || !telemetry.providerId || !telemetry.modelId || telemetry.durationMs === undefined) return;
      const capturedAt = new Date().toISOString();
      const key = `${telemetry.providerId.toLowerCase()}/${telemetry.modelId}`;
      void decisionClient.syncObservations({
        [key]: {
          providerId: telemetry.providerId,
          modelId: telemetry.modelId,
          productionEligible: false,
          telemetryStatus: "captured",
          telemetry: {
            capturedAt,
            measurementId: telemetry.requestIdHash ?? `openclaw-call-${capturedAt}`,
            metrics: { latencyMs: telemetry.durationMs, available: telemetry.outcome !== "error" && telemetry.outcome !== "failed", ...(telemetry.contextTokenBudget !== undefined ? { contextTokenBudget: telemetry.contextTokenBudget } : {}) },
          },
        },
      }).catch((error: unknown) => api.logger.warn(JSON.stringify({ event: "acce.telemetry.sync_failed", error: safeError(error) })));
    });
    api.on("llm_output", (event) => {
      const telemetry = sanitizeModelTelemetry(event);
      api.logger.info(JSON.stringify({ event: "acce.telemetry.llm_output", ...telemetry }));
    });

    const syncDiscoveryEvidence = async (snapshot: DiscoveryRefreshResult["snapshot"]): Promise<void> => {
      if (!decisionClient.configured) return;
      const minimized = Object.fromEntries(Object.entries(snapshot).map(([key, model]) => [
        key,
        {
          providerId: model.providerId,
          modelId: model.modelId,
          productionEligible: model.productionEligible,
          telemetryStatus: model.telemetryStatus,
          ...(model.telemetry ? {
            telemetry: {
              capturedAt: model.telemetry.capturedAt,
              measurementId: model.telemetry.measurementId,
              metrics: {
                latencyMs: model.telemetry.metrics.latencyMs,
                available: model.telemetry.metrics.available,
              },
            },
          } : {}),
        },
      ]));
      try {
        await decisionClient.syncObservations(minimized);
      } catch (error) {
        // Telemetry remains safely persisted in the inventory; sync can retry
        // on the next refresh and never makes discovery itself fail.
        api.logger.warn(JSON.stringify({
          event: "acce.decision.observation_sync_failed",
          error: safeError(error),
        }));
      }
    };

    const defaultStorePath = () =>
      resolveStorePath(config.inventoryPath ?? "~/.openclaw/acce-optimizer-data/inventory.json");
    let activeRefresh: Promise<DiscoveryRefreshResult> | undefined;

    const refreshDiscovery = async (
      ollamaUrl: string,
      storePath: string,
      logProgress: (event: unknown) => void = (event) => api.logger.info(JSON.stringify(event)),
    ): Promise<DiscoveryRefreshResult> => {
      if (activeRefresh) return activeRefresh;
      const operation = refreshModelDiscovery({
        readers: [createOllamaCatalogReader({ baseUrl: ollamaUrl })],
        store: createJsonFileDiscoveryStore(storePath),
        bootstrapTelemetry: createOllamaTelemetryBootstrap({ baseUrl: ollamaUrl }),
        onProgress(progress) {
          logProgress({ event: "acce.discovery.refresh.progress", ...progress });
        },
      });
      activeRefresh = operation;
      try {
        const result = await operation;
        await syncDiscoveryEvidence(result.snapshot);
        return result;
      } finally {
        if (activeRefresh === operation) activeRefresh = undefined;
      }
    };

    // Services own background work only in full Gateway runtime mode.
    if (api.registrationMode === "full") {
    api.registerService({
      id: "acce-optimizer-runtime-status",
      start() {
        if (!isEnabled(config)) return;
        const intervalSeconds = runtimeStatusRefreshIntervalSeconds;
        // Keep Gateway-backed CLI calls out of plugin startup and model resolution.
        runtimeStatusStartupTimer = setTimeout(() => { void refreshRuntimeStatus(); }, 15_000);
        runtimeStatusRefreshTimer = setInterval(() => { void refreshRuntimeStatus(); }, intervalSeconds * 1000);
      },
      stop() {
        if (runtimeStatusStartupTimer) clearTimeout(runtimeStatusStartupTimer);
        if (runtimeStatusRefreshTimer) clearInterval(runtimeStatusRefreshTimer);
        runtimeStatusAbortController?.abort();
        runtimeStatusStartupTimer = undefined;
        runtimeStatusRefreshTimer = undefined;
      },
    });

    api.registerService({
      id: "acce-optimizer-autodiscovery",
      start() {
        if (!isEnabled(config) || config.autoDiscoverOnStartup === false) return;
        void (async () => {
          const storePath = defaultStorePath();
          const existing = await createJsonFileDiscoveryStore(storePath).load();
          await syncDiscoveryEvidence(existing);
          if (!shouldRunInitialDiscovery({
            enabled: isEnabled(config),
            autoDiscoverOnStartup: config.autoDiscoverOnStartup !== false,
            inventoryRecordCount: Object.keys(existing).length,
          })) {
            api.logger.info(JSON.stringify({
              event: "acce.discovery.startup.skipped",
              reason: "inventory-already-initialized",
              records: Object.keys(existing).length,
            }));
            return;
          }
          const result = await refreshDiscovery(configuredOllamaUrl(config), storePath);
          api.logger.info(JSON.stringify({
            event: "acce.discovery.startup.completed",
            discovered: result.discovered,
            added: result.added,
            telemetryCaptured: result.telemetryCaptured,
            telemetryPending: result.telemetryPending,
            productionEligible: result.productionEligible,
          }));
        })().catch((error: unknown) => {
          api.logger.warn(JSON.stringify({
            event: "acce.discovery.startup.failed",
            error: safeError(error),
            retry: "manual refresh or next Gateway startup",
          }));
        });
      },
    });
    }

    api.registerCli((ctx) => {
      const root = ctx.program
        .command("acce-optimizer")
        .description("ACCE Optimizer governed model discovery");
      root
        .command("discovery-refresh")
        .description("Refresh the configured Ollama catalog and persist inventory")
        .requiredOption("--ollama-url <url>", "Explicit Ollama base URL (for example http://localhost:11434)")
        .requiredOption("--store <absolute-path>", "Absolute path for the private discovery inventory JSON")
        .action(async (options: { ollamaUrl: string; store: string }) => {
          const storePath = resolveStorePath(options.store);
          const result = await refreshDiscovery(options.ollamaUrl, storePath, (event) => {
            ctx.logger.info(JSON.stringify(event));
          });
          ctx.logger.info(JSON.stringify({
            event: "acce.discovery.refresh.completed",
            discovered: result.discovered,
            added: result.added,
            refreshed: result.refreshed,
            telemetryCaptured: result.telemetryCaptured,
            telemetryPending: result.telemetryPending,
            productionEligible: result.productionEligible,
          }));
          process.stdout.write(JSON.stringify({
            discovered: result.discovered,
            added: result.added,
            refreshed: result.refreshed,
            telemetryCaptured: result.telemetryCaptured,
            telemetryPending: result.telemetryPending,
            productionEligible: result.productionEligible,
            store: storePath,
          }, null, 2) + "\n");
        });
    }, {
      commands: ["acce-optimizer"],
      descriptors: [{
        name: "acce-optimizer",
        description: "ACCE Optimizer governed model discovery",
        hasSubcommands: true,
      }],
    });

    return {
      async "refresh-discovery"() {
        if (!isEnabled(config)) {
          throw new Error("ACCE Optimizer is disabled.");
        }
        const result = await refreshDiscovery(configuredOllamaUrl(config), defaultStorePath());
        api.logger.info(JSON.stringify({
          event: "acce.discovery.dashboard-refresh.completed",
          discovered: result.discovered,
          added: result.added,
          refreshed: result.refreshed,
          telemetryCaptured: result.telemetryCaptured,
          telemetryPending: result.telemetryPending,
          productionEligible: result.productionEligible,
        }));
        return {
          discovered: result.discovered,
          added: result.added,
          refreshed: result.refreshed,
          telemetryCaptured: result.telemetryCaptured,
          telemetryPending: result.telemetryPending,
          productionEligible: result.productionEligible,
        };
      },
    };
  },
});
