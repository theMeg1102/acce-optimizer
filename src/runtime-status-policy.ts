export type RuntimeStatusForPolicy = {
  modelsCapturedAt?: string;
  usageCapturedAt?: string;
  models?: Array<{ providerId: string; modelId: string; available: boolean | null }>;
  usage?: Array<{ providerId: string; remainingFraction: number }>;
};

const MAX_FUTURE_CLOCK_SKEW_MS = 30_000;
const LOCAL_PROVIDER_IDS = new Set([
  "ollama",
  "local",
  "localhost",
  "lmstudio",
  "llamacpp",
  "llama.cpp",
  "llama-cpp",
  "vllm",
  "localai",
]);

export function isFreshRuntimeTimestamp(timestamp: unknown, now: number, maxAgeMs: number): boolean {
  if (typeof timestamp !== "string" || !Number.isFinite(now) || !Number.isFinite(maxAgeMs) || maxAgeMs <= 0) return false;
  const capturedAt = Date.parse(timestamp);
  if (!Number.isFinite(capturedAt)) return false;
  const ageMs = now - capturedAt;
  return ageMs >= -MAX_FUTURE_CLOCK_SKEW_MS && ageMs <= maxAgeMs;
}

export function isRuntimeStatusFresh(
  status: RuntimeStatusForPolicy | null | undefined,
  now: number,
  maxAgeMs: number,
): boolean {
  return Boolean(
    status &&
    Array.isArray(status.models) &&
    Array.isArray(status.usage) &&
    isFreshRuntimeTimestamp(status.modelsCapturedAt, now, maxAgeMs),
  );
}

export function isKnownLocalProvider(providerId: string): boolean {
  return LOCAL_PROVIDER_IDS.has(providerId.trim().toLowerCase());
}

export function runtimeOverrideBlockReason(
  status: RuntimeStatusForPolicy | null | undefined,
  providerId: string,
  modelId: string,
  options: { now: number; maxAgeMs: number; requireFreshProviderUsage?: boolean },
): string | undefined {
  if (!isRuntimeStatusFresh(status, options.now, options.maxAgeMs)) {
    return "runtime-status-missing-or-stale";
  }

  const model = status?.models?.find((candidate) =>
    candidate.providerId === providerId && candidate.modelId === modelId
  );
  if (!model || model.available !== true) {
    return "model-not-confirmed-available";
  }

  if (options.requireFreshProviderUsage) {
    if (!isFreshRuntimeTimestamp(status?.usageCapturedAt, options.now, options.maxAgeMs)) {
      return "provider-usage-missing-or-stale";
    }
    const usage = status?.usage?.find((candidate) =>
      candidate.providerId.toLowerCase() === providerId.toLowerCase()
    );
    if (!usage || !Number.isFinite(usage.remainingFraction) || usage.remainingFraction <= 0 || usage.remainingFraction > 1) {
      return "provider-usage-missing-invalid-or-exhausted";
    }
  }

  return undefined;
}
