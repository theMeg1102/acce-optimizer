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
  return {
    async recordAndEvaluate(categories: readonly string[], threshold = 0.8): Promise<SimilarityWindowResult> {
      const operation = queue.then(async () => {
        const history = await loadUnlocked();
        const result = evaluateSimilarityWindow(categories, history, { threshold });
        await saveUnlocked(appendTaskObservation(history, categories));
        return result;
      });
      queue = operation.then(() => undefined, () => undefined);
      return operation;
    },
  };
}
