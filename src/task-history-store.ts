import { randomUUID } from "node:crypto";
import { chmod, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { appendTaskObservation, evaluateSimilarityWindow, type SimilarityWindowResult, type TaskObservation } from "./task-similarity.js";
const MAX_FILE_BYTES = 512 * 1024;
export function createTaskHistoryStore(path: string) {
  let queue: Promise<unknown> = Promise.resolve();
  async function loadUnlocked(): Promise<TaskObservation[]> {
    try {
      const raw = await readFile(path, "utf8");
      if (Buffer.byteLength(raw, "utf8") > MAX_FILE_BYTES) throw new Error("task history exceeds size limit");
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) throw new TypeError("task history must be a JSON array");
      return parsed.filter((item): item is TaskObservation => Boolean(item && typeof item === "object" && typeof (item as TaskObservation).signature === "string" && Array.isArray((item as TaskObservation).categories) && typeof (item as TaskObservation).observedAt === "string")).slice(-501);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
      throw error;
    }
  }
  async function saveUnlocked(history: readonly TaskObservation[]): Promise<void> {
    await mkdir(dirname(path), { recursive: true, mode: 0o700 });
    await chmod(dirname(path), 0o700);
    const temporary = `${path}.tmp`;
    await writeFile(temporary, `${JSON.stringify(history.slice(-501))}\n`, { encoding: "utf8", mode: 0o600 });
    await chmod(temporary, 0o600);
    await rename(temporary, path);
  }
  async function record(categories: readonly string[], threshold: number): Promise<{ consensus: SimilarityWindowResult; observationId: string }> {
    const history = await loadUnlocked();
    const consensus = evaluateSimilarityWindow(categories, history, { threshold });
    const observationId = randomUUID();
    await saveUnlocked(appendTaskObservation(history, categories, { observationId }));
    return { consensus, observationId };
  }
  return {
    async recordAndEvaluate(categories: readonly string[], threshold = 0.8): Promise<SimilarityWindowResult> {
      const operation = queue.then(() => record(categories, threshold)).then((result) => result.consensus);
      queue = operation.then(() => undefined, () => undefined);
      return operation;
    },
    async recordAndEvaluateWithId(categories: readonly string[], threshold = 0.8): Promise<{ consensus: SimilarityWindowResult; observationId: string }> {
      const operation = queue.then(() => record(categories, threshold));
      queue = operation.then(() => undefined, () => undefined);
      return operation;
    },
    async recordDecision(observationId: string, decision: { decisionId: string; routeId: string; providerId: string; modelId: string; rankedRoutes?: string[] }): Promise<boolean> {
      const operation = queue.then(async () => {
        const history = await loadUnlocked();
        const index = history.findIndex((item) => item.observationId === observationId);
        if (index < 0) return false;
        const updated = history.map((item, itemIndex) => itemIndex === index ? { ...item, decisionId: decision.decisionId, selectedRoute: { routeId: decision.routeId, providerId: decision.providerId, modelId: decision.modelId }, ...(decision.rankedRoutes?.length ? { rankedRoutes: decision.rankedRoutes.slice(0, 100) } : {}) } : item);
        await saveUnlocked(updated);
        return true;
      });
      queue = operation.then(() => undefined, () => undefined);
      return operation;
    },
    async getSuccessfulTemplate(categories: readonly string[]): Promise<string[] | undefined> {
      const operation = queue.then(async () => {
        const history = await loadUnlocked();
        const signature = categories.map((item) => item.trim().toLowerCase()).filter(Boolean).filter((item, index, all) => all.indexOf(item) === index).sort().join("|") || "general";
        const match = [...history].reverse().find((item) =>
          item.signature === signature && item.outcome === "success" &&
          Array.isArray(item.rankedRoutes) && item.rankedRoutes.length > 0
        );
        return match?.rankedRoutes?.filter((route): route is string => typeof route === "string" && route.length > 0).slice(0, 100);
      });
      queue = operation.then(() => undefined, () => undefined);
      const template = await operation;
      return template?.length ? template : undefined;
    },
    async recordOutcome(observationId: string, outcome: "success" | "failure"): Promise<boolean> {
      const operation = queue.then(async () => {
        const history = await loadUnlocked();
        const index = history.findIndex((item) => item.observationId === observationId);
        if (index < 0) return false;
        const updated = history.map((item, itemIndex) => itemIndex === index ? { ...item, outcome } : item);
        await saveUnlocked(updated);
        return true;
      });
      queue = operation.then(() => undefined, () => undefined);
      return operation;
    },
  };
}
