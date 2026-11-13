import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const isolatedHome = mkdtempSync(join(tmpdir(), "acce-openclaw-build-"));
const configPath = join(isolatedHome, "openclaw.json");
const manifestPath = resolve("openclaw.plugin.json");
const authoredManifest = JSON.parse(readFileSync(manifestPath, "utf8"));

try {
  // The authoring CLI initializes OpenClaw state while building UI assets.
  // Keep it away from the developer's real config and database, which may
  // have been migrated by a newer Gateway than this plugin's pinned CLI.
  writeFileSync(configPath, "{}\n", { mode: 0o600 });
  const env = {
    ...process.env,
    HOME: isolatedHome,
    USERPROFILE: isolatedHome,
    OPENCLAW_HOME: isolatedHome,
    OPENCLAW_STATE_DIR: isolatedHome,
    OPENCLAW_CONFIG_PATH: configPath,
  };
  const command = process.platform === "win32" ? "openclaw.cmd" : "openclaw";
  const result = spawnSync(command, ["plugins", "build", "--root", "."], {
    cwd: process.cwd(),
    env,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.error) throw result.error;
  if (result.signal) {
    console.error(`OpenClaw plugin build terminated by signal ${result.signal}`);
    process.exitCode = 1;
  } else {
    process.exitCode = result.status ?? 1;
  }
  if (process.exitCode === 0) {
    // OpenClaw's asset builder emits runtime UI metadata, but some CLI builds
    // normalize configSchema.properties away. Preserve the authored config
    // contract while retaining generated controlUi/runtime metadata.
    const generatedManifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    generatedManifest.configSchema = authoredManifest.configSchema;
    generatedManifest.uiHints = authoredManifest.uiHints;
    writeFileSync(manifestPath, `${JSON.stringify(generatedManifest, null, 2)}\n`, { mode: 0o644 });
  }
} finally {
  rmSync(isolatedHome, { recursive: true, force: true });
}
