import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const manifestPath = join(root, "openclaw.plugin.json");
if (!existsSync(manifestPath)) {
  throw new Error("Build did not produce openclaw.plugin.json");
}
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));

if (manifest.id !== "acce-optimizer") {
  throw new Error(`Unexpected plugin id in manifest: ${String(manifest.id)}`);
}
if (manifest.version !== pkg.version) {
  throw new Error(`Plugin manifest version ${String(manifest.version)} does not match package version ${pkg.version}`);
}
if (!existsSync(join(root, "dist", "index.js"))) {
  throw new Error("Build did not produce dist/index.js for runtimeExtensions");
}
if (!manifest.controlUi) {
  throw new Error("Build did not publish native Control UI metadata in openclaw.plugin.json");
}
const uiRoot = join(root, "dist", "control-ui");
if (!existsSync(uiRoot)) {
  throw new Error("Build did not produce dist/control-ui assets");
}
const uiFiles = readdirSync(uiRoot, { recursive: true }).filter((entry) =>
  typeof entry === "string" && /\.(?:js|css)$/u.test(entry),
);
if (uiFiles.length === 0) {
  throw new Error("Native Control UI bundle directory contains no JavaScript or CSS assets");
}
if (!manifest.configSchema || manifest.configSchema.type !== "object") {
  throw new Error("Plugin manifest is missing its object configSchema");
}

console.log(JSON.stringify({
  id: manifest.id,
  version: manifest.version,
  runtimeEntry: "dist/index.js",
  controlUi: manifest.controlUi,
  controlUiAssetCount: uiFiles.length,
  configSchema: "present",
}, null, 2));
