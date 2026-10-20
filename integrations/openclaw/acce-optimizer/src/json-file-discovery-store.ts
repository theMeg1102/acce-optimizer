import { randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename, rm, stat } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";
import type { DiscoverySnapshot } from "./discovery.js";
import type { DiscoveryStore } from "./discovery-coordinator.js";

const MAX_STORE_BYTES = 5 * 1024 * 1024;

function validateSnapshot(value: unknown): DiscoverySnapshot {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("discovery store must contain a JSON object");
  }
  const snapshot = value as Record<string, unknown>;
  for (const [key, candidate] of Object.entries(snapshot)) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
      throw new TypeError(`invalid discovery record: ${key}`);
    }
    const model = candidate as Record<string, unknown>;
    if (model.key !== key || typeof model.providerId !== "string" ||
        typeof model.modelId !== "string" || model.productionEligible !== false) {
      throw new TypeError(`invalid or unsafe discovery record: ${key}`);
    }
    if (model.telemetryStatus !== "pending" && model.telemetryStatus !== "captured") {
      throw new TypeError(`invalid telemetry state for discovery record: ${key}`);
    }
    if (typeof model.userAdded !== "boolean") {
      throw new TypeError(`invalid user-added state for discovery record: ${key}`);
    }
  }
  return value as DiscoverySnapshot;
}

/**
 * Durable JSON persistence for an explicitly configured absolute path.
 * Writes are atomic and private to the current OS user (0600). This is
 * suitable for a single Gateway process; multi-process deployments should
 * inject a transactional database-backed DiscoveryStore instead.
 */
export function createJsonFileDiscoveryStore(filePath: string): DiscoveryStore {
  if (!isAbsolute(filePath)) {
    throw new TypeError("discovery store path must be absolute");
  }
  const target = resolve(filePath);

  return {
    async load() {
      let info;
      try {
        info = await stat(target);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") return {};
        throw error;
      }
      if (!info.isFile()) throw new TypeError("discovery store path must be a regular file");
      if (info.size > MAX_STORE_BYTES) throw new RangeError("discovery store exceeds 5 MiB safety limit");
      const raw = await readFile(target, "utf8");
      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch {
        throw new TypeError("discovery store contains invalid JSON; refusing to reset inventory");
      }
      return validateSnapshot(parsed);
    },

    async save(snapshot) {
      const validated = validateSnapshot(snapshot);
      const serialized = JSON.stringify(validated, null, 2) + "\n";
      if (Buffer.byteLength(serialized, "utf8") > MAX_STORE_BYTES) {
        throw new RangeError("discovery store exceeds 5 MiB safety limit");
      }
      await mkdir(dirname(target), { recursive: true, mode: 0o700 });
      const temporary = `${target}.${randomUUID()}.tmp`;
      let handle;
      try {
        handle = await open(temporary, "wx", 0o600);
        await handle.writeFile(serialized, "utf8");
        await handle.sync();
        await handle.close();
        handle = undefined;
        await rename(temporary, target);
      } finally {
        if (handle) await handle.close().catch(() => undefined);
        await rm(temporary, { force: true }).catch(() => undefined);
      }
    },
  };
}
