import { execFile as nodeExecFile } from "node:child_process";

export type RuntimeModelStatus = {
  providerId: string;
  modelId: string;
  available: boolean | null;
  contextWindow?: number;
  contextTokens?: number;
};

export type RuntimeProviderUsage = {
  providerId: string;
  remainingFraction: number;
};

export type OpenClawRuntimeStatus = {
  modelsCapturedAt: string;
  usageCapturedAt: string;
  models: RuntimeModelStatus[];
  usage: RuntimeProviderUsage[];
};

type CliResult = { stdout: string; stderr: string };
type CliRunner = (file: string, args: string[], timeoutMs: number, signal?: AbortSignal) => Promise<CliResult>;

function runCli(file: string, args: string[], timeoutMs: number, signal?: AbortSignal): Promise<CliResult> {
  return new Promise((resolve, reject) => {
    nodeExecFile(file, args, {
      encoding: "utf8",
      timeout: timeoutMs,
      maxBuffer: 4 * 1024 * 1024,
      windowsHide: true,
      ...(signal ? { signal } : {}),
    }, (error, stdout, _stderr) => {
      if (error) {
        const code = error && typeof error === "object" && "code" in error ? String(error.code).slice(0, 40) : "unknown";
        // CLI stderr can contain account/provider diagnostics; never surface it in logs.
        reject(new Error(`OpenClaw CLI ${args.slice(0, 2).join(" ")} failed (code ${code}); details omitted`));
        return;
      }
      resolve({ stdout: String(stdout), stderr: String(stderr) });
    });
  });
}

function object(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function positiveInteger(value: unknown): number | undefined {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : undefined;
}

function parseModelRows(value: unknown): RuntimeModelStatus[] {
  const root = object(value);
  const rows = root?.models;
  if (!Array.isArray(rows)) throw new Error("openclaw models list JSON omitted models[]");
  const result: RuntimeModelStatus[] = [];
  for (const item of rows) {
    const row = object(item);
    const key = row?.key;
    if (typeof key !== "string") continue;
    const separator = key.indexOf("/");
    if (separator < 1 || separator === key.length - 1) continue;
    const providerId = key.slice(0, separator).trim();
    const modelId = key.slice(separator + 1).trim();
    if (!providerId || !modelId) continue;
    const available = typeof row?.available === "boolean" ? row.available : null;
    const contextWindow = positiveInteger(row?.contextWindow);
    const contextTokens = positiveInteger(row?.contextTokens);
    result.push({
      providerId,
      modelId,
      available,
      ...(contextWindow ? { contextWindow } : {}),
      ...(contextTokens ? { contextTokens } : {}),
    });
  }
  return result;
}

function parseUsage(value: unknown): { capturedAt: string; usage: RuntimeProviderUsage[] } {
  const root = object(value);
  const usageRoot = object(root?.usage);
  const updatedAt = usageRoot?.updatedAt;
  if (typeof updatedAt !== "number" || !Number.isFinite(updatedAt) || updatedAt <= 0) {
    throw new Error("openclaw status JSON omitted a valid usage.updatedAt");
  }
  const capturedAt = new Date(updatedAt).toISOString();
  const providers = usageRoot?.providers;
  if (!Array.isArray(providers)) throw new Error("openclaw status JSON omitted usage.providers[]");
  const result: RuntimeProviderUsage[] = [];
  for (const item of providers) {
    const provider = object(item);
    if (typeof provider?.provider !== "string" || provider.error !== undefined) continue;
    const windows = provider.windows;
    if (!Array.isArray(windows) || windows.length === 0) continue;
    const used = windows.map((entry) => object(entry)?.usedPercent);
    if (used.some((percent) => typeof percent !== "number" || !Number.isFinite(percent) || percent < 0 || percent > 100)) continue;
    // The most constrained active provider window governs the remaining quota.
    const remainingFraction = Math.max(0, 1 - Math.max(...used as number[]) / 100);
    result.push({ providerId: provider.provider.trim(), remainingFraction });
  }
  return { capturedAt, usage: result };
}

export async function readOpenClawRuntimeStatus(options: {
  cliPath?: string;
  timeoutMs?: number;
  now?: () => number;
  runCli?: CliRunner;
  signal?: AbortSignal;
} = {}): Promise<OpenClawRuntimeStatus> {
  const cliPath = options.cliPath?.trim() || "openclaw";
  const timeoutMs = options.timeoutMs ?? 15_000;
  const runner = options.runCli ?? runCli;
  // These are documented, read-only CLI surfaces. Do not use private Gateway RPC.
  const modelsResult = await runner(cliPath, ["models", "list", "--all", "--json"], timeoutMs, options.signal);
  const models = parseModelRows(JSON.parse(modelsResult.stdout));
  let usageCapturedAt = "";
  let usage: RuntimeProviderUsage[] = [];
  try {
    const usageResult = await runner(cliPath, ["status", "--usage", "--json", "--timeout", String(Math.max(1000, timeoutMs - 3000))], timeoutMs, options.signal);
    const parsedUsage = parseUsage(JSON.parse(usageResult.stdout));
    usageCapturedAt = parsedUsage.capturedAt;
    usage = parsedUsage.usage;
  } catch {
    // Model availability can still safely admit local routes; missing/stale quota
    // data makes quota-metered cloud routes ineligible in the decision service.
  }
  return {
    modelsCapturedAt: new Date((options.now ?? Date.now)()).toISOString(),
    usageCapturedAt,
    models,
    usage,
  };
}
