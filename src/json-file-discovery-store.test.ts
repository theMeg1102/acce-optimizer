import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { createJsonFileDiscoveryStore } from "./json-file-discovery-store.js";
import { upsertDiscoveredModel } from "./discovery.js";

const directories: string[] = [];

afterEach(async () => {
  await Promise.all(directories.splice(0).map((directory) => rm(directory, { recursive: true, force: true })));
});

async function tempStorePath(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "acce-discovery-"));
  directories.push(directory);
  return join(directory, "inventory.json");
}

describe("durable discovery JSON store", () => {
  it("round-trips inventory atomically and creates a private file", async () => {
    const path = await tempStorePath();
    const store = createJsonFileDiscoveryStore(path);
    expect(await store.load()).toEqual({});

    const snapshot = upsertDiscoveredModel({}, {
      providerId: "ollama",
      modelId: "qwen2.5:7b",
      source: "ollama",
      observedAt: "2026-10-19T12:00:00Z",
    });
    await store.save(snapshot);

    expect(await store.load()).toEqual(snapshot);
    expect(JSON.parse(await readFile(path, "utf8"))["ollama/qwen2.5:7b"].productionEligible).toBe(false);
    expect((await stat(path)).mode & 0o777).toBe(0o600);
  });

  it("requires an absolute path and rejects unsafe records", async () => {
    expect(() => createJsonFileDiscoveryStore("inventory.json")).toThrow(/absolute/);
    const path = await tempStorePath();
    const store = createJsonFileDiscoveryStore(path);
    await expect(store.save({
      "openai/model": {
        key: "openai/model",
        providerId: "openai",
        modelId: "model",
        telemetryStatus: "pending",
        userAdded: false,
        productionEligible: true,
      } as never,
    })).rejects.toThrow(/unsafe/);
  });

  it("refuses malformed JSON instead of silently discarding historical inventory", async () => {
    const path = await tempStorePath();
    const store = createJsonFileDiscoveryStore(path);
    await store.save({});
    const { writeFile } = await import("node:fs/promises");
    await writeFile(path, "{broken", "utf8");
    await expect(store.load()).rejects.toThrow(/invalid JSON/);
  });

  it("rejects oversized stores", async () => {
    const path = await tempStorePath();
    const { writeFile } = await import("node:fs/promises");
    await writeFile(path, " ".repeat(5 * 1024 * 1024 + 1), "utf8");
    await expect(createJsonFileDiscoveryStore(path).load()).rejects.toThrow(/5 MiB/);
  });
});
