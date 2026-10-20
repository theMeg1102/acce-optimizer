import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

type PluginPackage = {
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

describe("OpenClaw 2026.10.5 compatibility metadata", () => {
  it("pins SDK, peer dependency, and plugin API range to the validated host patch", () => {
    const exactHostRange = ">=2026.10.5 <2026.10.6";
    expect(packageJson.peerDependencies.openclaw).toBe(exactHostRange);
    expect(packageJson.devDependencies.openclaw).toBe("2026.10.5");
    expect(packageJson.openclaw.compat.pluginApi).toBe(exactHostRange);
    expect(packageJson.openclaw.build.openclawVersion).toBe("2026.10.5");
  });

  it("declares both the source entry and compiled runtime entry", () => {
    expect(packageJson.openclaw.extensions).toContain("./src/index.ts");
    expect(packageJson.openclaw.runtimeExtensions).toContain("./dist/index.js");
  });
});
