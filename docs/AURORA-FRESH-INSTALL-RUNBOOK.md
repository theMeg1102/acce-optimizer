# Fresh installation runbook — Aurora / OpenClaw 2026.10.5

Status: **installation in progress, not production-ready**. This runbook is the canonical checklist for packaging a reproducible ACCE installation. Update it as additional steps are validated. Do not treat observations as production authorization.

## Baseline and observed results (2026-11-12/13)

- Repo: `theMeg1102/acce-optimizer`, PR #5 branch `feature/openclaw-1.0.0-openclaw-2026.10.5`, source checkout `/tmp/acce-latest.arxe03/repo`.
- OpenClaw Gateway container: `openclaw-202698-openclaw-gateway-1`, image `ghcr.io/openclaw/openclaw:2026.10.5`; running and healthy.
- Node plugin: ACCE 0.1.3 installed from built local archive and reloaded successfully, generation 4. `plugins inspect`: enabled, origin global, shape non-capability, capability mode none, provenance-invalid because installed from local archive. **Do not relabel it as trusted or treat plugins.allow as provenance validation.**
- Native hooks confirmed in compiled `dist/index.js`: `before_model_resolve`, `agent_end`, `model_call_started`, `model_call_ended`, `llm_output`. Runtime logs confirm hook execution, telemetry, task outcome learning, and catalog observation. Log `acce.decision.unavailable` reason `decision-service-not-configured`: plugin keeps OpenClaw default model. `providersWithUsage:0` / `usageFresh:false`: no trustworthy provider quota data.
- Python bridge entry point in `pyproject.toml`: `acce-decision-server = acce_optimizer.core.decision_server:main`. Python package version 0.1.0, distinct from Node plugin version 0.1.3.
- Aurora Python 3.14.4: package installed successfully; earlier CI Python matrix covered 3.10–3.13, **not 3.14**.
- No running ACCE decision-server container, and `command -v acce-decision-server` returned no host executable before installation.
- Old sprint registries and fixtures exist on Aurora but **must not be imported**. User explicitly requested a fresh isolated installation.

## Fresh Python installation — executed successfully

1. Create new persistent directory: `mkdir -p /home/mark/acce-production`.
2. From `/tmp/acce-latest.arxe03/repo`, copy source only (not historical state or build outputs):
   ```bash
   tar --exclude='./.venv' --exclude='./node_modules' --exclude='./dist' --exclude='./.git' --exclude='./coverage' -cf - . | tar -xf - -C /home/mark/acce-production
   ```
3. Create isolated environment: `python3 -m venv /home/mark/acce-production/.venv`.
4. Install wheel into that environment:
   ```bash
   /home/mark/acce-production/.venv/bin/python -m pip install /home/mark/acce-production
   ```
   Result: `Successfully installed acce-optimizer-0.1.0`. This is an installation, **not** a running service.
5. Do not run a production daemon, alter the OpenClaw config, or expose a network port until registry, security, and smoke tests are ready.

**Final installer requirements:** automate these steps idempotently; use a versioned release artifact and checksum instead of a transient /tmp checkout; isolate runtime state from code; choose supported/tested Python; verify package and executable; make changes reversible; do not overwrite existing installations or state; provide service lifecycle, least-privilege permissions, network isolation, authenticated HTTPS/TLS transport between host and container, health checks, rollback and uninstall procedures. Never put secrets in Git or logs.

## Fresh inventory discovery — observed, not authorized

Read-only Ollama endpoint on Aurora host: `http://127.0.0.1:11434`.

```bash
curl -fsS http://127.0.0.1:11434/api/tags | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(m["name"]) for m in d.get("models",[])]'
```

Observed model names:
- Local conversational candidates: `deepseek-r1:14b`, `phi4:14b`, `gemma3:12b`, `gemma4:12b-it-qat`, `qwen3:14b`, `gemma4:e4b`, `gemma3n:e4b`, `qwen3:8b`.
- Exclude `nomic-embed-text:latest` from text-generation routes (embedding model).
- Exclude `gemma4:31b-cloud` from initial local-only registry (cloud model).
- Discovery alone does **not** authorize any model as production-eligible.

Read-only model metadata query:
```bash
curl -fsS http://127.0.0.1:11434/api/show -H 'Content-Type: application/json' -d '{"model":"gemma4:12b-it-qat"}' | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"capabilities":d.get("capabilities"),"model_info":{k:v for k,v in d.get("model_info",{}).items() if "context_length" in k},"parameters":d.get("parameters")},indent=2))'
```

Observed for `gemma4:12b-it-qat`:
- Ollama capabilities: `completion`, `vision`, `audio`, `tools`, `thinking`.
- Reported model context length: `gemma4.context_length = 262144` tokens. **This is model metadata, not proof of effective runtime context**; OpenClaw telemetry previously showed `contextTokenBudget:32768` for this model, so effective cap must be measured/conservatively bounded.
- Model parameters: `temperature 1`, `top_k 64`, `top_p 0.95`.
- No new benchmarked quality or latency score established by this metadata query. Previous runtime durations are telemetry, not a calibrated benchmark.

## Registry requirements and release gates

No production registry was found in the fresh checkout; `examples/registry.json` is an example only. Older sprint files are excluded by user request. Do not copy or promote fixtures.

The canonical `CapabilityRegistry.from_production_snapshot` calls `validate_production_registry` (in `src/acce_optimizer/core/registry.py`). This requires, among other things:
- `registry_mode:production`, `inventory_status:complete`, non-placeholder snapshot/policy/config/evidence IDs, timezone-aware `measured_at`.
- Consistent expected model/local/cloud counts; nonempty capabilities, models and route instances.
- Model metadata: provider-qualified reference, resource type, availability, operational status, context window, measured latency, evidence IDs, quality score, supported tasks, privacy and tools support.
- Route metadata must agree with model inventory and measured evidence; no fabricated quality, quota, privacy or latency.
- Exact provider/model pairs must intersect OpenClaw effective catalog; no unapproved model overrides.
- Production registry must pass `CapabilityRegistry.from_production_snapshot` and real bridge decision smoke tests. A structurally valid JSON file alone is not enough.

## Pending for final installable product

- [ ] Establish repeatable, permissioned model discovery and benchmark/evaluation pipeline for local models; capture provenance and timestamped evidence, including effective context and tool behavior.
- [ ] Generate **new** strict production registry from verified evidence and explicit operator approval, not from fixtures or inferred scores.
- [ ] Test Python 3.14 compatibility or pin a CI-tested Python version; run Python test suite in isolated install.
- [ ] Configure private persistent ACCE decision server with explicit registry, token, TLS proxy/tunnel as needed; no public exposure. Check `GET /health` and authenticated `POST /v1/decide`.
- [ ] Connect Node plugin `decisionServiceUrl` / `decisionServiceToken` (or corresponding environment variables) without leaking secrets; validate network reachability from Gateway container.
- [ ] Start with shadow/non-mutating verification; note that current `shadow` branch returns before calling decision service, so bridge evaluation needs a separate explicit smoke test before adaptive activation.
- [ ] Validate runtime status freshness, availability, quotas, cost governance and host override permissions; preserve fail-open OpenClaw default on errors.
- [ ] Verify capability/provenance behavior using official OpenClaw packaging; do not claim a locally packed archive is trusted.
- [ ] Add automated installer/upgrader, environment template (without secrets), service definition, preflight, post-install smoke, rollback and operator docs. Include this runbook in release checklist.
- [ ] Record each newly validated Aurora deployment step and update this file in Git as development proceeds.

## Operational guardrails

- No `set -e`, `exit`, or destructive shell snippets that terminate an interactive SSH session on failure.
- Do not restart Gateway, enable adaptive routing, reinstall the plugin, delete state, or expose a port without a deliberate change plan and operator approval.
- Keep previous sprint directories intact but completely isolated from the new deployment.

## Ollama capability inventory — confirmed read-only API observations

Discovery procedure: query `GET /api/tags`, exclude the embedding model `nomic-embed-text:latest` and cloud-tagged `gemma4:31b-cloud`, then `POST /api/show` for each of eight local candidates. The observed output below is the raw model-advertised context length, **not** a measured effective OpenClaw context window or production authorization.

| Model | Ollama-reported context | Advertised capabilities |
|---|---:|---|
| `deepseek-r1:14b` | 131072 | tools, thinking, completion |
| `phi4:14b` | 16384 | completion |
| `gemma3:12b` | 131072 | completion, vision |
| `gemma4:12b-it-qat` | 262144 | completion, vision, audio, tools, thinking |
| `qwen3:14b` | 40960 | completion, tools, thinking |
| `gemma4:e4b` | 131072 | completion, vision, audio, tools, thinking |
| `gemma3n:e4b` | 32768 | completion |
| `qwen3:8b` | 40960 | completion, tools, thinking |

All eight `/api/show` requests succeeded. Source: operator-run read-only Ollama API queries on Aurora. `gemma4:12b-it-qat` previously showed an effective OpenClaw telemetry budget of 32768; do not confuse that with its 262144 Ollama model-advertised limit.

**Final installer requirement:** implement repeatable local discovery as a non-mutating preflight; retain raw evidence with timestamp, source, provider/model identity and model digest when available. Require explicit operator approval, verified OpenClaw catalog membership and benchmarked latency/quality before production authorization. Do not treat Ollama-advertised `tools`, `thinking`, `vision` or `audio` as proof of end-to-end OpenClaw behavior.

## Hardware-agnostic resource discovery and benchmarking

The final product must **not** hard-code GPU vendors, PCI IDs, model-specific memory allocations, CUDA/ROCm/Vulkan requirements, host memory sizes, or vendor-specific diagnostic tools. Installer and runtime should work on CPU-only systems as well as supported GPU-accelerated systems, with appropriate capability detection and clear fallback behavior.

- Discover available CPU, RAM, swap, accelerators, memory and inference backends dynamically using portable interfaces where possible; use optional platform/vendor adapters only after capability detection.
- Do not install drivers or vendor tools automatically as part of probing.
- `ollama ps` returned headers only during this installation: no model was loaded at the time. This is not evidence of CPU-only inference.
- Querying explicit backend-related environment variables returned no matching values. An empty result does **not** identify the active Ollama backend.
- For reproducible benchmarks, measure actual execution placement and effective context under load, run one model at a time, and record cold/warm timing, tokens, latency and memory use.
- Treat observed hardware characteristics as **per-installation evidence**, stored outside the product's version-controlled defaults. Never promote a single machine's hardware into a universal installer assumption.
- Do not interrupt active workloads or unload models without operator approval.

## Concurrent-workload inference observation — not a clean benchmark

Operator explicitly reported a local agent request running during this test. A separate `POST /api/generate` request to Ollama for `gemma4:e4b`, prompt "Responde únicamente con la palabra OK.", `stream:false`, `num_ctx:2048`, `num_predict:16`, `keep_alive:5m`, returned:
- `response: OK`
- `total_duration:15480778600` ns (15.4808 s)
- `load_duration:15180338948` ns (15.1803 s)
- `prompt_eval_count:24`, `eval_count:2`, `eval_duration:71527000` ns (0.0715 s)

Immediately following, `ollama ps` reported:
- `gemma4:12b-it-qat`: `7.6 GB`, `100% GPU`, context `32768`.
- `gemma4:e4b`: `148 MB`, `100% GPU`, context `2048`.

Interpretation: Ollama reported both models as fully GPU-resident at that instant; this does **not** prove simultaneous token generation or an idle-machine benchmark. The very small reported residency for `gemma4:e4b` should be recorded as observed, not generalized as typical model memory consumption. Separate cold-load, prompt evaluation, generation, and queue/wall-clock effects. The workload was concurrent with the user's live agent, so do not assign production latency/quality scores from this single run. Avoid further benchmark calls until the active agent finishes or the operator authorizes interference. Final installer remains hardware-agnostic; no host-specific GPU identification is required.

## Second Ollama inference observation — cold load, 128-token cap

Operator ran `POST /api/generate` for `gemma4:e4b` with Spanish prompt "Explica en tres frases qué es una API REST.", `stream:false`, `keep_alive:5m`, `num_ctx:2048`, `num_predict:128`, `temperature:0`. Reported response metrics:
- `total_duration:24.955` seconds
- `load_duration:21.827` seconds
- `prompt_eval_duration:0.214` seconds; `prompt_eval_count:27`
- `eval_duration:2.906` seconds; `eval_count:128`
- `tokens_per_second:44.05` computed from generated tokens and eval duration.

This was **not** a warm-only measurement: model load accounted for ~87.5% of total time. Generated tokens reached the configured `num_predict` cap of 128, so completion quality and whether the answer was truncated cannot be determined from the reported fields; the script did not print `done_reason` or the text. Do not use the result as a definitive latency or quality score. Installer/evaluator requirements: record `done_reason`, distinguish cold vs warm, and measure actual generation throughput separately from end-to-end latency. Avoid machine-specific benchmark defaults in product code.

## Sequential identical Ollama calls — unexpected reload-like latency

Operator executed two sequential `POST /api/generate` calls to `gemma4:e4b` with identical prompt "Responde únicamente: OK", `stream:false`, `keep_alive:10m`, `num_ctx:2048`, `num_predict:16`, `temperature:0`. Results:
- Call 1: total `0.693s`, load `0.382s`, generated `2` tokens, `done_reason:stop`.
- Call 2: total `16.426s`, load `16.151s`, generated `2` tokens, `done_reason:stop`.

The second request was ~23.7x slower and its load duration dominated (~98.3%). This is consistent with a reload or backend initialization, but the cause is **unverified**. Do not assert eviction, memory pressure, or GPU backend change without corroborating Ollama logs and configuration. A keep_alive setting does not by itself prove residency throughout concurrent activity. Evaluator should track model residency and reload events, isolate contention and queue effects, and distinguish load time from inference latency. No production scoring or universal hardware assumptions from this observation.

## Ollama systemd configuration inspection — runtime-specific evidence

Operator ran `systemctl cat ollama`. Service starts `/usr/local/bin/ollama serve` under user/group `ollama`, with `Restart=always`. The drop-in override explicitly sets:
- `OLLAMA_HOST=0.0.0.0:11434` (binds all interfaces; review network access/firewall separately before production).
- `OLLAMA_IGPU_ENABLE=1` (present as operator-configured environment variable; do not generalize this vendor/backend-specific setting to the installer).

No explicit `OLLAMA_MAX_LOADED_MODELS` or `OLLAMA_NUM_PARALLEL` appeared in the systemd unit/drop-in. Their **effective** values or Ollama defaults were not established by this output. This does not explain the previously observed ~16-second load duration, and no cause should be asserted. Continue with read-only effective-environment/log diagnostics before proposing changes. Do not modify the running Ollama/OpenClaw services or publish host-specific values as product defaults.
