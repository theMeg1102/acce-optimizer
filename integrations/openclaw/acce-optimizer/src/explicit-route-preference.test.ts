import { describe, expect, it } from "vitest";
import { extractExplicitRoutePreference } from "./explicit-route-preference.js";

const routes = [
  { providerId: "local-provider", modelId: "Reader" },
  { providerId: "cloud-provider", modelId: "model" },
  { providerId: "cloud-provider", modelId: "model/large" },
  { providerId: "cloud-provider", modelId: "model/fast" },
];

describe("explicit current-turn route preference", () => {
  it("extracts an exact route after an explicit English or Spanish directive", () => {
    expect(extractExplicitRoutePreference("For this task, please use local-provider/Reader.", routes))
      .toEqual({ providerId: "local-provider", modelId: "Reader" });
    expect(extractExplicitRoutePreference("Para esta tarea, prefiero cloud-provider/model/large.", routes))
      .toEqual({ providerId: "cloud-provider", modelId: "model/large" });
  });

  it("does not infer preference from a route mention alone or a negated directive", () => {
    expect(extractExplicitRoutePreference("The log mentions local-provider/Reader.", routes)).toBeUndefined();
    expect(extractExplicitRoutePreference("Do not use local-provider/Reader; compare the options.", routes)).toBeUndefined();
    expect(extractExplicitRoutePreference("No uses local-provider/Reader.", routes)).toBeUndefined();
  });

  it("fails closed on ambiguous or conflicting route mentions", () => {
    expect(extractExplicitRoutePreference("Use local-provider/Reader or cloud-provider/model/fast.", routes)).toBeUndefined();
    expect(extractExplicitRoutePreference("Use local-provider/Reader, then prefer cloud-provider/model/fast.", routes)).toBeUndefined();
  });

  it("does not mistake a shorter model ID for a prefix of a longer model ID", () => {
    expect(extractExplicitRoutePreference("Use cloud-provider/model/large.", routes))
      .toEqual({ providerId: "cloud-provider", modelId: "model/large" });
  });

  it("matches exact configured identity, preserving model-ID case", () => {
    expect(extractExplicitRoutePreference("Use local-provider/reader.", routes)).toBeUndefined();
    expect(extractExplicitRoutePreference("Use unconfigured-provider/unknown.", routes)).toBeUndefined();
  });

  it("does not retain or return prompt text", () => {
    const prompt = "Use local-provider/Reader for this confidential request: private phrase";
    expect(extractExplicitRoutePreference(prompt, routes)).toEqual({ providerId: "local-provider", modelId: "Reader" });
    expect(JSON.stringify(extractExplicitRoutePreference(prompt, routes))).not.toContain("private phrase");
  });
});
