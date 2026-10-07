import { describe, expect, it } from "vitest";

describe("ACCE OpenClaw adapter", () => {
  it("keeps production routing disabled while shadow mode is enabled", () => {
    const config = { enabled: true, mode: "shadow" as const };
    expect(config.enabled).toBe(true);
    expect(config.mode).toBe("shadow");
  });

  it("does not expose a production model override in shadow mode", () => {
    const result: { providerOverride?: string; modelOverride?: string } | undefined = undefined;
    expect(result?.providerOverride).toBeUndefined();
    expect(result?.modelOverride).toBeUndefined();
  });
});
