export type RuntimeStatusForPolicy = {
  modelsCapturedAt?: string;
  models?: Array<{ providerId: string; modelId: string; available: boolean | null }>;
  usage?: Array<{ providerId: string; remainingFraction: number }>;
};

const MAX_FUTURE_CLOCK_SKEW_MS = 30_000;

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

export function runtimeOverrideBlockReason(
  status: RuntimeStatusForPolicy | null | undefined,
  providerId: string,
  modelId: string,
  options: { now: number; maxAgeMs: number },
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

  return undefined;
}
