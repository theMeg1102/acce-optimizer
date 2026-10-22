type UnknownRecord = Record<string, unknown>;
export type RuntimeModel = { providerId: string; modelId: string; configured: boolean; modelType?: string; contextWindow?: number; contextTokens?: number; maxTokens?: number; input?: string[]; cost?: { input?: number; output?: number; cacheRead?: number; cacheWrite?: number } };
function record(value: unknown): UnknownRecord | undefined { return value && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : undefined; }
function finitePositive(value: unknown): number | undefined { return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : undefined; }
/** Read only model metadata from OpenClaw's effective in-memory config. Never copy credentials. */
export function readConfiguredRuntimeModels(config: unknown): RuntimeModel[] {
  const root = record(config); if (!root) return [];
  const models = record(root.models); const providers = record(models?.providers); if (!providers) return [];
  const result: RuntimeModel[] = [];
  for (const [providerId, providerValue] of Object.entries(providers)) {
    const provider = record(providerValue); const providerModels = Array.isArray(provider?.models) ? provider.models : [];
    for (const modelValue of providerModels) {
      const model = record(modelValue); const modelId = typeof model?.id === "string" ? model.id.trim() : ""; if (!modelId) continue;
      const costValue = record(model?.cost);
      const hasTieredPricing = Array.isArray(costValue?.tieredPricing) && costValue.tieredPricing.length > 0;
      const input = Array.isArray(model?.input) ? model.input.filter((item): item is string => typeof item === "string") : undefined;
      const contextWindow = finitePositive(model?.contextWindow) ?? finitePositive(provider?.contextWindow);
      const contextTokens = finitePositive(model?.contextTokens) ?? finitePositive(provider?.contextTokens) ?? contextWindow;
      const maxTokens = finitePositive(model?.maxTokens) ?? finitePositive(provider?.maxTokens);
      result.push({ providerId, modelId, configured: true, ...(typeof model?.type === "string" ? { modelType: model.type } : {}), ...(contextWindow ? { contextWindow } : {}), ...(contextTokens ? { contextTokens } : {}), ...(maxTokens ? { maxTokens } : {}), ...(input?.length ? { input } : {}), ...(costValue && !hasTieredPricing ? { cost: { ...(typeof costValue.input === "number" && Number.isFinite(costValue.input) && costValue.input >= 0 ? { input: costValue.input } : {}), ...(typeof costValue.output === "number" && Number.isFinite(costValue.output) && costValue.output >= 0 ? { output: costValue.output } : {}), ...(typeof costValue.cacheRead === "number" && Number.isFinite(costValue.cacheRead) && costValue.cacheRead >= 0 ? { cacheRead: costValue.cacheRead } : {}), ...(typeof costValue.cacheWrite === "number" && Number.isFinite(costValue.cacheWrite) && costValue.cacheWrite >= 0 ? { cacheWrite: costValue.cacheWrite } : {}) } } : {}) });
    }
  }
  return result.sort((a, b) => `${a.providerId}/${a.modelId}`.localeCompare(`${b.providerId}/${b.modelId}`));
}
export type SanitizedModelCall = { providerId?: string; modelId?: string; durationMs?: number; outcome?: string; requestIdHash?: string; inputTokens?: number; outputTokens?: number; totalTokens?: number };
function finiteNonNegative(value: unknown): number | undefined { return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined; }
/** Minimize OpenClaw hook payloads to provider/model and aggregate metrics only. */
export function sanitizeModelTelemetry(value: unknown): SanitizedModelCall {
  const event = record(value) ?? {}; const usage = record(event.usage) ?? record(event.tokenUsage) ?? {}; const result: SanitizedModelCall = {};
  const providerId = event.provider ?? event.providerId; const modelId = event.model ?? event.modelId; const durationMs = event.durationMs ?? event.elapsedMs ?? event.duration; const outcome = event.outcome ?? event.status; const requestIdHash = event.upstreamRequestIdHash ?? event.requestIdHash;
  const inputTokens = usage.input ?? usage.inputTokens ?? usage.promptTokens; const outputTokens = usage.output ?? usage.outputTokens ?? usage.completionTokens; const totalTokens = usage.total ?? usage.totalTokens;
  if (typeof providerId === "string") result.providerId = providerId.slice(0, 128);
  if (typeof modelId === "string") result.modelId = modelId.slice(0, 256);
  if (finiteNonNegative(durationMs) !== undefined) result.durationMs = finiteNonNegative(durationMs);
  if (typeof outcome === "string") result.outcome = outcome.slice(0, 64);
  if (typeof requestIdHash === "string") result.requestIdHash = requestIdHash.slice(0, 128);
  if (finiteNonNegative(inputTokens) !== undefined) result.inputTokens = finiteNonNegative(inputTokens);
  if (finiteNonNegative(outputTokens) !== undefined) result.outputTokens = finiteNonNegative(outputTokens);
  if (finiteNonNegative(totalTokens) !== undefined) result.totalTokens = finiteNonNegative(totalTokens);
  return result;
}
