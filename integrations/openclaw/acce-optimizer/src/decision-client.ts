export type AcceDecision = {
  decision_id?: string;
  decision_state?: string;
  status?: string;
  providerOverride?: string | null;
  modelOverride?: string | null;
  selected_route?: { route_id?: string; provider_id?: string; model_used?: string } | null;
  engine?: string;
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

  return {
    configured: Boolean(endpoint),
    async decide(request: Record<string, unknown>): Promise<AcceDecision | undefined> {
      if (!endpoint) return undefined;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetchImpl(endpoint, {
          method: "POST",
          headers: {
            accept: "application/json",
            "content-type": "application/json",
            ...(params.bearerToken ? { authorization: `Bearer ${params.bearerToken}` } : {}),
          },
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
