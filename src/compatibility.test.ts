import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

type PluginPackage = {
  name: string;
  version: string;
  peerDependencies: { openclaw: string };
  devDependencies: { openclaw: string };
  openclaw: {
    compat: { pluginApi: string };
    build: { openclawVersion: string };
    extensions: string[];
    runtimeExtensions: string[];
  };
};

const packageJson = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf8"),
) as PluginPackage;
const pluginManifest = JSON.parse(
  readFileSync(new URL("../openclaw.plugin.json", import.meta.url), "utf8"),
) as { id: string; version: string; configSchema: { properties: Record<string, { default?: unknown; enum?: unknown[] }> } };

describe("OpenClaw 2026.10.5 compatibility metadata", () => {
  it("aligns the package and native manifest at version 0.1.3", () => {
    expect(packageJson.name).toBe("openclaw-plugin-acce-optimizer");
    expect(packageJson.version).toBe("0.1.3");
    expect(pluginManifest.id).toBe("acce-optimizer");
    expect(pluginManifest.version).toBe(packageJson.version);
  });

  it("pins SDK, peer dependency, and plugin API range to the validated host patch", () => {
    const exactHostRange = ">=2026.10.5 <2026.10.6";
    expect(packageJson.peerDependencies.openclaw).toBe(exactHostRange);
    expect(packageJson.devDependencies.openclaw).toBe("2026.10.5");
    expect(packageJson.openclaw.compat.pluginApi).toBe(exactHostRange);
    expect(packageJson.openclaw.build.openclawVersion).toBe("2026.10.5");
  });

  it("declares the decision bridge and makes adaptive graph routing the default", () => {
    expect(pluginManifest.configSchema.properties.mode.default).toBe("adaptive");
    expect(pluginManifest.configSchema.properties.mode.enum).toEqual(["adaptive", "shadow"]);
    expect(pluginManifest.configSchema.properties.decisionServiceUrl).toBeDefined();
    expect(pluginManifest.configSchema.properties.decisionServiceToken).toBeDefined();
    expect(pluginManifest.configSchema.properties.allowExternalNetwork.default).toBe(false);
    expect(pluginManifest.configSchema.properties.maxCloudCostUsd.default).toBe(0);
  });

  it("declares both the source entry and compiled runtime entry", () => {
    expect(packageJson.openclaw.extensions).toContain("./src/index.ts");
    expect(packageJson.openclaw.runtimeExtensions).toContain("./dist/index.js");
  });
});
