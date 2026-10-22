export function shouldRunInitialDiscovery(params: {
  enabled: boolean;
  autoDiscoverOnStartup: boolean;
  inventoryRecordCount: number;
}): boolean {
  return params.enabled && params.autoDiscoverOnStartup && params.inventoryRecordCount === 0;
}
