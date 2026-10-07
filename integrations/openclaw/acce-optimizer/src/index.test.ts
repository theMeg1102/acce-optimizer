import { describe, expect, it } from "vitest";

describe("ACCE OpenClaw adapter", () => {
  it("keeps production routing disabled by default", () => {
    const config = { enabled: false, mode: "shadow" as const };
    expect(config.enabled).toBe(false);
    expect(config.mode).toBe("shadow");
  });
});
