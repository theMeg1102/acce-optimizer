import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { readOpenClawRuntimeStatus } from "./openclaw-cli-runtime-status.js";

describe("OpenClaw CLI subprocess smoke test", () => {
  it("executes the documented read-only commands through the real child-process runner", async () => {
    const directory = await mkdtemp(join(tmpdir(), "acce-openclaw-cli-smoke-"));
    const callsPath = join(directory, "calls.txt");
    const cliPath = join(directory, "openclaw-fixture");
    const callsPathForShell = callsPath.replaceAll("'", "'\\''");
    const script = `#!/bin/sh
printf '%s\\n' "$*" >> '${callsPathForShell}'
if [ "$1" = "models" ] && [ "$2" = "list" ]; then
  printf '%s\\n' '{"models":[{"key":"ollama/qwen3:8b","available":true,"contextWindow":32768}]}'
  exit 0
fi
if [ "$1" = "status" ] && [ "$2" = "--usage" ]; then
  printf '%s\\n' '{"usage":{"updatedAt":1792539466217,"providers":[{"provider":"cloud-provider","windows":[{"label":"5h","usedPercent":25}]}]}}'
  exit 0
fi
exit 41
`;
    try {
      await writeFile(cliPath, script, { mode: 0o700 });
      await chmod(cliPath, 0o700);

      const result = await readOpenClawRuntimeStatus({
        cliPath,
        timeoutMs: 5_000,
        now: () => 1792539467000,
      });

      expect(result.models).toEqual([
        { providerId: "ollama", modelId: "qwen3:8b", available: true, contextWindow: 32768 },
      ]);
      expect(result.usage).toEqual([{ providerId: "cloud-provider", remainingFraction: 0.75 }]);
      expect(result.usageCapturedAt).toBe(new Date(1792539466217).toISOString());
      expect((await readFile(callsPath, "utf8")).trim().split("\\n")).toEqual([
        "models list --all --json",
        "status --usage --json --timeout 2000",
      ]);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });

  it("fails closed when the CLI process exits unsuccessfully without exposing stderr", async () => {
    const directory = await mkdtemp(join(tmpdir(), "acce-openclaw-cli-failure-"));
    const cliPath = join(directory, "openclaw-fixture");
    try {
      await writeFile(cliPath, "#!/bin/sh\nprintf '%s\\n' 'sensitive provider diagnostic' >&2\nexit 17\n", { mode: 0o700 });
      await chmod(cliPath, 0o700);

      await expect(readOpenClawRuntimeStatus({ cliPath, timeoutMs: 5_000 }))
        .rejects.toThrow("OpenClaw CLI models list failed (code 17); details omitted");
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
});
