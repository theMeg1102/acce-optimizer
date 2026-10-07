# ACCE Input Contract

ACCE keeps decision inputs explicit so that the runtime remains vendor-neutral and does not embed a machine-specific model inventory.

## Decision request

A decision request is a JSON object with these core fields:

- `request_id`: unique request identifier.
- `task_class`: task category used for route matching.
- `summary`: concise task description.
- `required_capabilities`: capabilities that must be satisfied.
- `profile`: routing preference profile.
- `constraints`: economic, quota, search, and context constraints.
- `governance`: approval, validation, and clarification controls.

The request parser supplies documented defaults for optional fields. For a first evaluation, the example in `examples/request.json` is sufficient.

### Important request controls

The following controls are especially relevant to routing:

- `external_network_allowed`: whether routes requiring external network access may be selected.
- `tools_allowed`: whether tool access is permitted.
- `max_cloud_cost_usd`: maximum cloud cost for the decision.
- `max_latency_ms`: maximum accepted latency.
- `min_quality_score`: minimum accepted quality score.
- `search_budget.max_candidate_routes`: maximum candidate routes evaluated.
- `cloud_quota_remaining_fraction`: trusted remaining cloud quota fraction.
- `monthly_cloud_budget_usd` and `monthly_cloud_spend_usd`: trusted budget state.
- Context controls define current, estimated input, expected output, compaction, reset, and hard-limit token state.

ACCE does not infer provider quota values or convert subscription quota into monetary cost.

## Registry

A normal decision registry is a JSON object containing an `instances` list. Each instance describes a candidate route. The runtime normalizes optional route metadata using safe defaults.

A route can declare:

- `route_id`
- `capability_id`
- `instance_id`
- `provider_id`
- `resource_type`
- `supported_task_classes`
- `availability`
- `quality_score`
- `estimated_latency_ms`
- `estimated_cloud_cost_usd`
- `model_used`
- `quota_metered`
- `monetary_metered`
- `context_window_tokens`

The supported resource types are:

- `local_model`
- `cloud_model`

The supported availability values are:

- `available`
- `unavailable`
- `disabled`

The example registry is intentionally a non-production local route. It contains no provider credentials, no machine-specific inventory, and no claim of measured production performance.

## Production registry

Production validation is deliberately stricter than normal decision input parsing.

A production registry must declare:

- `registry_mode: "production"`
- `inventory_status: "complete"`
- `snapshot_id`
- `policy_snapshot_id`
- `configuration_snapshot_id`
- `inventory_evidence_id`
- `measured_at`
- expected local/cloud/total model counts
- a non-empty capability inventory
- a complete model inventory
- a non-empty route inventory

Production models and routes must be internally consistent. Route latency and quality must match the measured model inventory, every inventoried model must have a route, and required evidence identifiers must be present.

The supported operational statuses are:

- `production`
- `experimental`
- `disabled`

Production validation rejects placeholder values and does not enable production execution. Do not copy the example registry into a production registry. Generate production registry data from trusted, measured inventory and evidence.

## Running a decision

From the repository root:

```bash
acce --run-decision \
  --request examples/request.json \
  --registry examples/registry.json
```

The command produces an authoritative deterministic execution plan. ACCE plans the route; it does not execute the selected model or external action.

Adaptive shadow evaluation uses the same inputs:

```bash
acce --run-adaptive-shadow \
  --request examples/request.json \
  --registry examples/registry.json
```

Production registry validation is separate:

```bash
acce --validate-production-registry --registry PATH
```

Replace `PATH` with an actual registry file. The literal string `PATH` is only documentation notation and is not a valid input file.
