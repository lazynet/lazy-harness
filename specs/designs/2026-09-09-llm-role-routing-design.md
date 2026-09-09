# Role-routed inference: one resolution seam for every model the harness calls

**Status:** proposed
**Date:** 2026-09-09
**Decision record:** [ADR-039](../adrs/039-role-routed-inference.md)
**Relates to:** [ADR-033](../adrs/033-llm-backend-abstraction.md) (LLM backend abstraction), [ADR-004](../adrs/004-agent-adapter-pattern.md) (agent adapter), [ADR-032](../adrs/032-agent-adapter-completeness.md), [ADR-038](../adrs/038-exec-envelope-cost-provenance.md) (exec envelope), [ADR-035](../adrs/035-capability-registry.md) (capability registry), [ADR-021](../adrs/021-async-response-grading.md)

## Problem

The harness has **two independent ways to make a model produce tokens**, and they know nothing about each other.

| | `lh exec` | `LLMBackend` |
|---|---|---|
| Introduced by | ADR-004, envelope in ADR-038 | ADR-033 |
| Config | `[agent].type` | `[compound_loop].backend` |
| Registry | `agents/registry.py` — `claude-code`, `null` | `llm/registry.py` — `claude`, `ollama`, `mlx`, `openai-compatible` |
| Model selection | `--tier` → adapter maps it | `[compound_loop].model` |
| Contract | JSON envelope `lh.exec/v1` | bare `str` |
| Cost and attribution | pricing table, transcript billing, `--workload` | none |
| Timeout ownership | kills the child's process group | `subprocess`/`httpx` timeout |
| Callers | external tools | `knowledge/compound_loop.py`, `cli/memory_cmd.py` |
| Non-Anthropic providers | **none** | Ollama, MLX, any OpenAI-compatible endpoint |

Three consequences follow, and each is a defect on its own.

**Both doors know how to spawn `claude -p`.** `agents/claude_code.py:166` builds the argv for one; `llm/claude.py:26` builds a different argv for the other. Two implementations of the same subprocess call, with different flags, drifting independently.

**Only one door counts what it spends.** `lh exec` records attribution before the spawn and bills from the transcript even when a run is killed (`cli/exec_cmd.py:113`). The compound loop records nothing. Every distillation run is a Haiku call absent from `metrics.db` — an observability gap that already exists and grows with usage.

**The door that supports local models is the one nobody can reach.** `[compound_loop].backend` is a single global value. Turning it to `ollama` routes *everything* local, including the distillation and grading calls where output quality is the point. There is no way to say "classify cheaply, distil well", and no way for a caller outside this repo to request local inference at all.

### What the corpus says

Two measurements shaped the design rather than confirming it.

Session classification is **not** a candidate consumer. Of 1194 exported sessions, the substring rules of ADR-028 resolve 1163 — `work` 500, `personal` 499, `vault` 159 — leaving 31 (2.6%) at `other`. Replacing a deterministic, free, instant classifier to address 2.6% of cases is a downgrade.

Structured output is load-bearing, but not for the expected reason. Against a live Ollama on this machine, `qwen2.5-coder:7b` returned clean JSON both with and without a schema — the fence-and-prose breakage that `parse_response` (`knowledge/compound_loop.py:813`) exists to absorb did not occur. What did occur: asked to pick from `debug|feature|docs|other` without a schema, it answered `"bug"`. **The schema buys domain conformance, not JSON hygiene.**

## Decision

One place resolves *who answers* and executes the call. Two front ends sit on it: the CLI, for callers outside this repo, and a function, for callers inside it. Which backend serves a call is chosen by a named **role**, declared in config.

### 1. The seam

New module `src/lazy_harness/llm/invoke.py`:

```python
@dataclass(frozen=True)
class InferenceError:
    kind: str
    message: str


@dataclass(frozen=True)
class InferenceResult:
    output: str
    success: bool
    model: str
    backend: str
    duration_ms: int
    error: InferenceError | None


def run_inference(
    prompt: str,
    *,
    role: str,
    cfg: Config,
    timeout: int,
    schema: dict | None = None,
) -> InferenceResult:
    ...
```

`run_inference` resolves the role to a backend and model, calls it, times it, and maps every exception to a named `kind`. **It never raises.** A caller that gets an `InferenceResult` has a complete account of what happened.

Two front ends:

- **`lh exec --role <name>`** — resolves the role. If it names an inference backend, `run_inference` runs and the result maps onto the `lh.exec/v1` envelope. If it names an agent, today's path runs unchanged.
- **In-process** — `knowledge/compound_loop.py` and `cli/memory_cmd.py` call `run_inference` directly. `invoke_llm` is deleted; its None-on-failure contract is subsumed by `success`.

The compound-loop worker does **not** shell out to `lh exec`. It would spawn a subprocess of itself per session for no gain. "One way to do it" names a single resolution-and-execution seam, not a single operating-system process.

### 2. The envelope grows a `mode`

`lh.exec/v1` carries agent-shaped fields — `num_turns`, `cache_read_tokens`, `cache_creation_tokens`, `session_id` — that an inference call cannot fill. Left as bare nulls they are ambiguous: a consumer cannot tell "does not apply to this mode" from "the run failed silently". That ambiguity is the exact failure ADR-038 named when it split a mute failure into `no-envelope` and `agent-error`.

The envelope gains:

```json
"mode": "inference" | "agent"
```

Non-null always. A consumer reading `mode: "inference"` knows the null token fields are structural.

`cost_usd` stays null for a local backend and keeps `cost_source: null` alongside it, preserving the ADR-038 invariant that the two are non-null together.

### 3. Config

```toml
[llm]
default_role = "distill"

[llm.backends.haiku]
type  = "claude"
model = "claude-haiku-4-5-20251001"

[llm.backends.local]
type  = "ollama"
model = "qwen2.5-coder:7b"
# base_url optional; the ollama and mlx aliases carry presets

[llm.backends.openrouter]
type        = "openai-compatible"
base_url    = "https://openrouter.ai/api/v1"
model       = "..."
api_key_env = "OPENROUTER_API_KEY"

[llm.roles]
distill  = "haiku"
classify = "local"
```

A role names a backend. A backend names a type, a model, and the options that type needs. The `type` values are exactly the ones `llm/registry.py` already registers, so ADR-033's registry is reused rather than replaced.

**Why roles and not tiers.** `HEADLESS_TIERS = ("fast", "balanced", "deep")` (`agents/base.py:9`) describes a *capability level*, and the adapter maps it to a model. Whether a unit of work can run **without tools** is an orthogonal axis, and it is the one that decides whether an inference backend can serve the call at all. An external caller asking for `--tier fast` with tools granted must never land on Ollama, which has no tools to grant. Routing on the tier would make that silent. The role is the routing key; the tier remains the agent's model selector.

### 4. Structured output

The Protocol gains one optional keyword:

```python
def complete(
    self, prompt: str, model: str, timeout: int, *, schema: dict | None = None
) -> str: ...
```

- `OpenAICompatibleBackend` sends `response_format` with a `json_schema`. Verified against a live Ollama during design.
- `ClaudeBackend` ignores `schema` — `claude -p` exposes no equivalent flag — and callers keep the `parse_response` fallback.

The rule for callers: a schema is **required** wherever a value feeds a decision or becomes an index key, and optional for free text. The measured failure mode is an out-of-enum value, which is invisible until something downstream reads it.

### 5. Failure taxonomy

`InferenceError.kind` names the evidence, not the symptom, because what a caller does next differs:

| kind | Cause | Caller's next move |
|---|---|---|
| `backend-unreachable` | endpoint down, binary absent | retry, or abandon the batch |
| `timeout` | exceeded the budget | retry with less input |
| `schema-violation` | responded, failed validation | **do not retry the same model** — it will repeat |
| `empty` | no output | treat as an abstention |
| `backend-error` | 4xx/5xx, or CLI exit ≠ 0 | read `message` |

### 6. No automatic fallback between backends

A failing local backend does **not** silently fall through to a paid one. Two reasons, both concrete:

1. A silent fallback to a billed model is the precise mechanism by which a cost optimisation becomes a cost surprise. Without reading the envelope, the operator never learns it happened.
2. It hides a broken local backend. Ollama down would keep "working", surfacing only on an invoice.

No safety net is needed for the in-repo caller: the compound loop already degrades correctly. A failed call skips the session and writes the deterministic slim handoff (`knowledge/compound_loop.py:1245`) — a path that is already written and tested.

A caller that wants a fallback retries with a different `--role`. Explicit, and visible in the envelope.

### 7. Secrets

`api_key_env` names an environment variable; the value never appears in config. This reuses the `url_env` mechanism in `monitoring/sink_setup.py` verbatim, including its three properties:

- Resolved **at call time**, never at parse time, so the value is never serialised to disk.
- Falls back to the secrets file, which must be owner-only (`sink_setup.py:81`).
- The parser rejects `api_key` and `api_key_env` together.

`lh doctor` names the variable and reports whether it resolves, never the value.

This matters here and not in ADR-033 because `config.toml` is a chezmoi `.tmpl`: a literal key committed there lands in the dotfiles repository.

### 8. Verification surface

The consumer that motivates this work lives in another repository, so nothing in this one would otherwise exercise a non-default role end to end. `[llm.roles] classify = "local"` could be broken with the whole suite green — the failure mode CLAUDE.md records as "an implemented hook does not run until it is wired".

Two additions close it, and both serve the external consumer too:

- **`lh exec --role <name> --dry-run`** emits the resolved plan — backend, model, `base_url`, whether the key resolves — and spends no tokens. `--dry-run` already exists on the agent path (`cli/exec_cmd.py:246`); this extends it to inference.
- **`lh doctor`** validates the whole table: every role resolves to a defined backend, every backend is reachable, every `api_key_env` is present. Today it checks only the single `[compound_loop]` backend (`cli/doctor_cmd.py:188`).

## Contract for external consumers

A caller outside this repository sees only this. It is the stable surface; everything above is implementation.

```bash
printf '%s' "$PROMPT" | lh exec --role classify --workload file-triage
```

- The prompt travels on **stdin**. Never in argv — these prompts inline whole files and `ARG_MAX` is a ceiling nothing checks.
- Exactly one JSON envelope goes to stdout. The backend's stderr passes through untouched.
- `--dry-run` returns the resolved plan without spending tokens; use it as a preflight.
- `--workload <label>` attributes the run in `metrics.db`.

Envelope fields a consumer should read:

| Field | Meaning |
|---|---|
| `schema` | `"lh.exec/v1"` — check it |
| `mode` | `"inference"` here; explains why token fields are null |
| `success` | whether output is usable |
| `output` | the model's text |
| `error.kind` | one of the six kinds above, non-null whenever `success` is false |
| `cost_usd` | null for a local backend; non-null with `cost_source` |
| `backend`, `model` | which one actually answered |

`--role` and `--tier` are mutually exclusive; `--role` with an inference backend and `--allow-tools` is a **hard error**, never a silent downgrade to a backend that has no tools.

## Migration

`[compound_loop].backend` and `.model` keep working. The loader maps them to a synthetic role named `distill` and warns once. ADR-033's fields are deprecated, not removed; no existing config breaks.

Precedence when both forms are present: the explicit `[llm]` table wins, and the loader warns that the `[compound_loop]` values are being ignored.

## Verification

- `run_inference` against a stub backend — the pattern ADR-033 established for `invoke_llm`.
- **Config round trip** on `[llm]`: save → load → save → load. The new-document path and the merge-onto-existing path are tested separately.
- **Deprecation path**: a config carrying only `[compound_loop].backend` resolves the synthetic `distill` role and warns once; a config carrying both warns and prefers `[llm]`.
- **Envelope**: `mode` is non-null in both paths, and the agent path is unchanged against today's output.
- **Wrong-type and hostile input**: a role naming an undefined backend; an unknown `type`; `api_key` and `api_key_env` together; a null or non-table `[llm.roles]`.
- **Prove the guard guards**: removing the schema pass-through must fail a test. The assertion is the measured case — an out-of-enum value — restored by hand afterwards, never with `git checkout`, which would revert the implementation too.
- **The consumer parses the envelope**, not the test that wrote it. An `lh exec --role ... --dry-run` invocation is parsed by the real external client before this is considered done.

## Out of scope

- **A second agent adapter** (Codex, Gemini CLI). Those are agent CLIs with their own tool loops and belong in `agents/registry.py` behind ADR-004/ADR-032. This design neither delivers nor blocks one; it makes the *inference* axis pluggable, which is a different axis.
- **Automatic model selection** — a router that infers the best model per task. That requires a per-role quality signal that does not exist today; without one it is a hunch with more code. The hooks for a future attempt already exist (grading in ADR-021, workload attribution in ADR-037), and are deliberately not used here.
- **The file classifier itself.** It lives in another repository and consumes the contract above. Its safety properties — dry-run default, destination allowlist, confidence threshold, reversible manifest — are that repository's design, not this one's.

## Alternatives considered

**Register Ollama as an `AgentAdapter`.** Rejected. `AgentAdapter` is subprocess-shaped throughout — `resolve_binary`, `process_name`, `headless_argv`, `session_argv`, process-group teardown, transcript billing. An HTTP endpoint has none of these, so the adapter would return `None` or `[]` across half the Protocol: the `NullAdapter` shape, in production. Worse, `[agent].type` is global, so setting it to `ollama` would also change what `lh run` launches interactively. Wrong knob.

**Keep two doors and document the split.** Rejected, though defensible: agentic execution and single-turn inference genuinely differ. What decided it is that the split as drawn forces the cost-accounting machinery to be written twice — `lh exec` has it and the compound loop does not. A seam whose duplication cost is a real observability gap is cut in the wrong place.

**Route on the existing tier vocabulary.** Rejected. See §3: tiers describe capability level, not tool-freedom, and conflating them makes a tools-granted call silently reachable by a backend with no tools.
