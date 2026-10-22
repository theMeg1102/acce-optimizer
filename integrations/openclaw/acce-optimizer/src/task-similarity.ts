export type TaskObservation = {
  signature: string;
  observationId?: string;
  categories: string[];
  observedAt: string;
  outcome?: "success" | "failure" | "unknown";
  preference?: string;
};

export type SimilarityWindowResult = {
  eligible: boolean;
  sampleSize: number;
  matchingCount: number;
  matchingFraction: number;
  requiredMatches: number;
  signature: string;
  windowSizesEvaluated: number[];
  reason: "threshold_met" | "insufficient_history" | "threshold_not_met";
};

export type SimilarityPolicy = { threshold?: number; minimumWindow?: number };

function canonicalCategories(categories: readonly string[]): string[] {
  return [...new Set(categories.map((item) => item.trim().toLowerCase()).filter(Boolean))].sort();
}

export function taskSignature(categories: readonly string[]): string {
  const normalized = canonicalCategories(categories);
  return normalized.length ? normalized.join("|") : "general";
}

/**
 * Checks odd-sized history windows (5, 7, 9, ...) newest-first.
 * A default pattern is eligible only when at least threshold of observations
 * in a window share the current task signature. This is consensus, not a model score.
 * No window is fabricated when history is too short.
 */
export function evaluateSimilarityWindow(currentCategories: readonly string[], history: readonly TaskObservation[], policy: SimilarityPolicy = {}): SimilarityWindowResult {
  const threshold = policy.threshold ?? 0.8;
  const minimumWindow = policy.minimumWindow ?? 5;
  if (!Number.isFinite(threshold) || threshold <= 0 || threshold > 1) throw new RangeError("similarity threshold must be in (0, 1]");
  if (!Number.isInteger(minimumWindow) || minimumWindow < 1 || minimumWindow % 2 === 0) throw new RangeError("minimum similarity window must be a positive odd integer");
  const signature = taskSignature(currentCategories);
  const newestFirst = [...history.filter((item) => typeof item.signature === "string" && item.signature.length > 0)].reverse();
  // An unclassified "general" task is not a meaningful similarity class.
  // Never promote a broad catch-all signature into a default pattern.
  if (signature === "general") {
    return { eligible: false, sampleSize: 0, matchingCount: 0, matchingFraction: 0, requiredMatches: Math.ceil(minimumWindow * threshold), signature, windowSizesEvaluated: [], reason: "insufficient_history" };
  }
  const largestOddWindow = newestFirst.length % 2 === 1 ? newestFirst.length : newestFirst.length - 1;
  const windowSizesEvaluated: number[] = [];
  if (largestOddWindow < minimumWindow) return { eligible: false, sampleSize: largestOddWindow, matchingCount: 0, matchingFraction: 0, requiredMatches: Math.ceil(minimumWindow * threshold), signature, windowSizesEvaluated, reason: "insufficient_history" };
  let lastResult: SimilarityWindowResult | undefined;
  for (let size = minimumWindow; size <= largestOddWindow; size += 2) {
    windowSizesEvaluated.push(size);
    const window = newestFirst.slice(0, size);
    const matchingCount = window.filter((item) => item.signature === signature).length;
    const requiredMatches = Math.ceil(size * threshold);
    const matchingFraction = matchingCount / size;
    lastResult = { eligible: matchingCount >= requiredMatches, sampleSize: size, matchingCount, matchingFraction, requiredMatches, signature, windowSizesEvaluated: [...windowSizesEvaluated], reason: matchingCount >= requiredMatches ? "threshold_met" : "threshold_not_met" };
    if (lastResult.eligible) return lastResult;
  }
  return lastResult ?? { eligible: false, sampleSize: 0, matchingCount: 0, matchingFraction: 0, requiredMatches: Math.ceil(minimumWindow * threshold), signature, windowSizesEvaluated, reason: "insufficient_history" };
}

export function appendTaskObservation(history: readonly TaskObservation[], categories: readonly string[], options: { observationId?: string; outcome?: TaskObservation["outcome"]; preference?: string; observedAt?: string } = {}, maximumEntries = 501): TaskObservation[] {
  if (!Number.isInteger(maximumEntries) || maximumEntries < 5) throw new RangeError("maximum history entries must be an integer >= 5");
  const categoriesNormalized = canonicalCategories(categories);
  const observation: TaskObservation = { signature: taskSignature(categoriesNormalized), ...(options.observationId ? { observationId: options.observationId } : {}), categories: categoriesNormalized, observedAt: options.observedAt ?? new Date().toISOString(), outcome: options.outcome ?? "unknown", ...(options.preference ? { preference: options.preference } : {}) };
  return [...history, observation].slice(-maximumEntries);
}
