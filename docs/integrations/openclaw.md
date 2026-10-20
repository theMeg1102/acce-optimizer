# OpenClaw Integration

ACCE Optimizer integrates with OpenClaw through a native plugin adapter.

## Architecture

```
OpenClaw
    |
    | before_model_resolve
    v
ACCE OpenClaw Adapter
    |
    | DecisionRequest
    v
ACCE DecisionService
    |
    +-- governance
    +-- quota and cost
    +-- context
    +-- quality
    +-- latency
    +-- deterministic search
```

The ACCE core is provider-neutral and OpenClaw-independent. OpenClaw-specific behavior belongs only in the adapter.

## Current safety boundary

The first integration phase is shadow-only:

- OpenClaw remains authoritative for model selection.
- ACCE does not override the selected provider or model.
- Conversation access is controlled by OpenClaw's explicit plugin permission.
- ACCE production routing remains disabled.
- The adapter must not mutate OpenClaw sessions.

The OpenClaw plugin SDK is experimental. ACCE pins the adapter to the tested OpenClaw 2026.9.8 compatibility range and must be revalidated for later OpenClaw releases.

## Integration phases

1. **Shadow hook:** receive the model-resolution event without changing the selected model.
2. **Decision bridge:** construct a governed ACCE `DecisionRequest` and call the public decision service.
3. **Shadow comparison:** compare ACCE's decision with OpenClaw's authoritative selection.
4. **Production gate:** enable provider/model overrides only after explicit acceptance criteria are satisfied.
