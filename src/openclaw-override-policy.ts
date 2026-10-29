type RecordLike = Record<string, unknown>;
function record(value: unknown): RecordLike | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as RecordLike : undefined;
}

/**
 * Mirror OpenClaw's documented model-override opt-in before returning an
 * override from before_model_resolve. The host remains the final authority.
 */
export function isModelOverrideAllowed(config: unknown, pluginId: string, providerId: string, modelId: string): boolean {
  const root = record(config);
  const plugins = record(root?.plugins);
  const entries = record(plugins?.entries);
  const plugin = record(entries?.[pluginId]);
  const llm = record(plugin?.llm);
  if (llm?.allowModelOverride !== true) return false;
  const allowedModels = llm.allowedModels;
  if (allowedModels === undefined) return true;
  if (!Array.isArray(allowedModels) || allowedModels.some((item) => typeof item !== "string")) return false;
  return allowedModels.includes(`${providerId}/${modelId}`);
}
