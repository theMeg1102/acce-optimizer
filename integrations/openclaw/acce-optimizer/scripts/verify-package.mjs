import { spawnSync } from "node:child_process";

const result = spawnSync("npm", ["pack", "--dry-run", "--json"], {
  cwd: process.cwd(),
  encoding: "utf8",
  stdio: ["ignore", "pipe", "pipe"],
});
if (result.error) throw result.error;
if (result.status !== 0) {
  process.stderr.write(result.stderr || "");
  throw new Error(`npm pack --dry-run failed with exit code ${result.status}`);
}

let pack;
try {
  pack = JSON.parse(result.stdout);
} catch {
  throw new Error("npm pack --dry-run did not return valid JSON");
}
const entry = Array.isArray(pack) ? pack[0] : pack;
const packedFiles = entry?.files ?? [];
const files = new Set(packedFiles.map((file) => String(file.path ?? file).replace(/^package\//u, "")));
const required = [
  "package.json",
  "openclaw.plugin.json",
  "README.md",
  "dist/index.js",
];
const missing = required.filter((file) => !files.has(file));
const uiAssets = [...files].filter((file) =>
  /^dist\/control-ui\/.*\.(?:js|css)$/u.test(file),
);
if (uiAssets.length === 0) {
  missing.push("dist/control-ui/<generated JavaScript/CSS assets>");
}
if (missing.length > 0) {
  throw new Error(`Packed plugin is incomplete; missing: ${missing.join(", ")}. npm pack metadata: ${JSON.stringify({ entryKeys: Object.keys(entry ?? {}), fileCount: packedFiles.length, firstFiles: packedFiles.slice(0, 12) })}`);
}

console.log(JSON.stringify({
  package: entry.filename ?? `${entry.name ?? "plugin"}-${entry.version ?? "unknown"}`,
  packedFileCount: files.size,
  runtimeEntry: "present",
  manifest: "present",
  controlUiAssetCount: uiAssets.length,
}, null, 2));
