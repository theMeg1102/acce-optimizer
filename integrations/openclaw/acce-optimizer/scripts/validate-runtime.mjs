import { mkdir, rm, writeFile } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const validationRoot = join(packageRoot, ".openclaw-validation");
const stateDir = join(validationRoot, "state");
const configPath = join(validationRoot, "openclaw.json");

async function run(command, args, env) {
  return await new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: packageRoot,
      env,
      stdio: "inherit",
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} exited with code ${code}`));
    });
  });
}

const env = {
  ...process.env,
  OPENCLAW_STATE_DIR: stateDir,
  OPENCLAW_CONFIG_PATH: configPath,
};

try {
  await rm(validationRoot, { recursive: true, force: true });
  await mkdir(stateDir, { recursive: true });
  await writeFile(
    configPath,
    JSON.stringify({
      plugins: {
        load: {
          paths: [packageRoot],
        },
        allow: ["acce-optimizer"],
        entries: {
          "acce-optimizer": {
            enabled: true,
            hooks: {
              allowConversationAccess: true,
            },
          },
        },
      },
    }),
    "utf8",
  );

  const inspect = await new Promise((resolve, reject) => {
    const child = spawn(
      "openclaw",
      ["plugins", "inspect", "acce-optimizer", "--runtime", "--json"],
      {
        cwd: packageRoot,
        env,
        stdio: ["ignore", "pipe", "inherit"],
      },
    );
    let stdout = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve(stdout);
      else reject(new Error(`openclaw inspect exited with code ${code}`));
    });
  });

  const report = JSON.parse(inspect);

  function findPlugin(value) {
    if (!value || typeof value !== "object") {
      return null;
    }
    if (!Array.isArray(value) && value.id === "acce-optimizer") {
      return value;
    }
    for (const child of Array.isArray(value) ? value : Object.values(value)) {
      const match = findPlugin(child);
      if (match) {
        return match;
      }
    }
    return null;
  }

  const plugin = findPlugin(report);
  if (!plugin) {
    throw new Error(
      `Runtime inspection did not report acce-optimizer. Report keys: ${Object.keys(report).join(", ")}`,
    );
  }

  if (plugin.error) { throw new Error(`Runtime inspection reported plugin error: ${plugin.error}`); }

  const typedHooks = Array.isArray(plugin.typedHooks) ? plugin.typedHooks : [];
  const hookNames = typedHooks.map((hook) => hook?.name).filter(Boolean);
  if (!hookNames.includes("before_model_resolve")) {
    throw new Error(
      `Runtime inspection did not report before_model_resolve. Registered typed hooks: ${hookNames.join(", ") || "none"}`,
    );
  }

  if (plugin.shape && plugin.shape !== "hook-only") {
    throw new Error(`Expected hook-only plugin shape, got ${plugin.shape}.`);
  }

  if (plugin.policy?.allowConversationAccess !== true) {
    throw new Error("Runtime inspection did not report conversation-hook access.");
  }

  process.stdout.write("ACCE Optimizer OpenClaw runtime inspection passed.\n");
} finally {
  await rm(validationRoot, { recursive: true, force: true });
}
