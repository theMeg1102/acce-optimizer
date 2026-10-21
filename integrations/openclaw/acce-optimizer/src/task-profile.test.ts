import { describe, expect, it } from "vitest";
import { deriveTaskProfile } from "./task-profile.js";

describe("privacy-preserving task profiling", () => {
  it("extracts graph features without returning prompt content", () => {
    const profile = deriveTaskProfile("Please debug this Python script and analyze the architecture. secret-token-123");
    expect(profile.summary).toContain("coding");
    expect(profile.summary).toContain("analysis");
    expect(profile.summary).not.toContain("secret-token-123");
    expect(profile.summary).not.toContain("Please debug");
    expect(profile.urgency).toBe("normal");
  });

  it("marks urgency without sending the original text", () => {
    const profile = deriveTaskProfile("Fix this immediately");
    expect(profile.urgency).toBe("urgent");
    expect(profile.summary).toContain("urgent");
    expect(profile.summary).not.toContain("Fix this");
    expect(profile.categories).not.toContain("urgent");
  });
});
