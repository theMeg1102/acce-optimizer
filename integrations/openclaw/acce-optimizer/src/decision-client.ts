export type AcceDecision = {
  decision_id?: string;
  decision_state?: string;
  status?: string;
  providerOverride?: string | null;
  modelOverride?: string | null;
  selected_route?: { route_id?: string; provider_id?: string; model_used?: string } | null;
  ranking_result?: Array<{ rank?: number; route_id?: string; provider_id?: string; model_used?: string; score_percent?: number; effective_graph_cost?: number; estimated_cloud_cost_usd?: number }>;
  engine?: string;
  policy_mode?: string;
};

type FetchLike = (input: string | URL, init?: RequestInit) => Promise<Response>;

export function createDecisionClient(params: {
  baseUrl?: string;
  bearerToken?: string;
  timeoutMs?: number;
  fetchImpl?: FetchLike;
}) {
  const baseUrl = params.baseUrl?.trim();
  const timeoutMs = params.timeoutMs ?? 1500;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 10000) {
    throw new RangeError("decision timeout must be between 100 and 10000 ms");
  }
  let endpoint: URL | undefined;
  if (baseUrl) {
    endpoint = new URL(baseUrl);
    if (!["http:", "https:"].includes(endpoint.protocol) ||
        endpoint.username || endpoint.password || endpoint.search || endpoint.hash) {
      throw new TypeError("Invalid ACCE decision service URL");
    }
    endpoint.pathname = `${endpoint.pathname.replace(/\/$/u, "")}/v1/decide`;
  }
  const fetchImpl = params.fetchImpl ?? fetch;
  const observationsEndpoint = endpoint ? new URL(endpoint.href) : undefined;
  if (observationsEndpoint) {
    observationsEndpoint.pathname = observationsEndpoint.pathname.replace(/\/v1\/decide$/u, "/v1/observations");
  }

  function headers(): Record<string, string> {
    return {
      accept: "application/json",
      "content-type": "application/json",
      ...(params.bearerToken ? { authorization: `Bearer ${params.bearerToken}` } : {}),
    };
  }

  return {
    configured: Boolean(endpoint),
    async syncObservations(snapshot: Record<string, unknown>): Promise<boolean> {
      if (!observationsEndpoint) return false;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetchImpl(observationsEndpoint, {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({ snapshot }),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`ACCE observation sync returned HTTP ${response.status}`);
        return true;
      } finally {
        clearTimeout(timer);
      }
    },
    async decide(request: Record<string, unknown>): Promise<AcceDecision | undefined> {
      if (!endpoint) return undefined;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetchImpl(endpoint, {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({ request }),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`ACCE decision service returned HTTP ${response.status}`);
        const payload: unknown = await response.json();
        if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
          throw new TypeError("ACCE decision service response must be an object");
        }
        const decision = payload as AcceDecision;
        if (decision.status !== "execution_plan_ready" ||
            !decision.providerOverride || !decision.modelOverride) return decision;
        return decision;
      } finally {
        clearTimeout(timer);
      }
    },
  };
}
