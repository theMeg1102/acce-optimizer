import { describe, expect, it } from "vitest";
import { shouldRunInitialDiscovery } from "./autodiscovery-policy.js";

describe("first-run autodiscovery policy", () => {
  it("runs on an enabled first install with an empty inventory", () => {
    expect(shouldRunInitialDiscovery({
      enabled: true,
      autoDiscoverOnStartup: true,
      inventoryRecordCount: 0,
    })).toBe(true);
  });

  it("does not repeat startup discovery when an inventory already exists", () => {
    expect(shouldRunInitialDiscovery({
      enabled: true,
      autoDiscoverOnStartup: true,
      inventoryRecordCount: 10,
    })).toBe(false);
  });

  it("respects the user's startup discovery preference", () => {
    expect(shouldRunInitialDiscovery({
      enabled: true,
      autoDiscoverOnStartup: false,
      inventoryRecordCount: 0,
    })).toBe(false);
  });

  it("never runs while the plugin is disabled", () => {
    expect(shouldRunInitialDiscovery({
      enabled: false,
      autoDiscoverOnStartup: true,
      inventoryRecordCount: 0,
    })).toBe(false);
  });
});
