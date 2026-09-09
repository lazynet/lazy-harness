# ADR-039: Role-routed inference — one resolution seam, two front ends

**Status:** proposed
**Date:** 2026-09-09
**Design:** [`specs/designs/2026-09-09-llm-role-routing-design.md`](../designs/2026-09-09-llm-role-routing-design.md)
**Related:** ADR-033 (llm-backend-abstraction), ADR-004 (agent-adapter-pattern),
ADR-032 (agent-adapter-completeness), ADR-038 (exec-envelope-cost-provenance),
ADR-035 (capability-registry), ADR-021 (async-response-grading), ADR-037 (metric-event-v2)

## Context

ADR-033 gave the framework a provider-agnostic inference Protocol and four backends. ADR-004 and ADR-038 gave it a headless agent launcher with a versioned envelope, cost provenance and workload attribution. Both shipped. Neither knows the other exists.

The result is two independent ways to make a model produce tokens, split along a line nobody drew deliberately:

- `lh exec` owns the envelope, the timeout, the process-group teardown, transcript billing and attribution — and can only run Claude Code.
- `llm/registry.py` supports Ollama, MLX and any OpenAI-compatible endpoint — and returns a bare string, unaccounted for, reachable only from inside this package.

Three defects follow.

**The `claude -p` invocation exists twice.** `agents/claude_code.py:166` and `llm/claude.py:26` build different argv for the same binary and drift independently.

**Half the spend is invisible.** `lh exec` attributes a run before spawning and prices a killed run from its transcript. The compound loop records nothing, so every distillation call is absent from `metrics.db`.

**Local inference is unreachable in practice.** `[compound_loop].backend` is one global value: setting it to `ollama` routes distillation and grading local too, which is where output quality is the whole point. There is no way to express "classify cheaply, distil well", and no way for a caller outside this repository to request local inference at all.

Two measurements constrained the answer rather than confirming it. Session classification is not a candidate consumer — ADR-028's substring rules already resolve 1163 of 1194 exported sessions, leaving 2.6% at `other`. And structured output matters for a different reason than assumed: against a live Ollama, `qwen2.5-coder:7b` emitted clean JSON with and without a schema, but answered outside a declared enum when the schema was absent. The schema buys domain conformance, not JSON hygiene.

## Decision

**One place resolves who answers and executes the call. Two front ends sit on it. A named role decides which backend serves a given unit of work.**

`src/lazy_harness/llm/invoke.py` gains `run_inference(prompt, *, role, cfg, timeout, schema=None) -> InferenceResult`. It resolves the role, calls the backend, times it, and maps every exception to a named `kind`. It never raises.

The front ends are `lh exec --role <name>` for callers outside this repository, and the function itself for callers inside it. The compound-loop worker calls the function; it does not shell out to `lh exec`, which would spawn a subprocess of itself per session. **One way to do it names a single resolution-and-execution seam, not a single OS process.**

Five properties are load-bearing:

1. **The routing key is a role, not a tier.** `HEADLESS_TIERS` describes capability level; whether work can run *without tools* is an orthogonal axis, and it is the one deciding whether an inference backend can serve a call at all. Routing on the tier would let a tools-granted request land silently on a backend with no tools.

2. **The envelope declares its `mode`.** Agent-shaped fields an inference call cannot fill — `num_turns`, `cache_*`, `session_id` — are otherwise ambiguous nulls, indistinguishable from a failure that said nothing. That is the exact ambiguity ADR-038 named. The schema stays `lh.exec/v1` under a stated invariant: **an envelope carrying `mode: "agent"` is field-for-field what v1 emitted before**, the sole addition being `mode` itself. Without that invariant, changing envelope shape inside a version would demand v2; with it, no existing consumer moves.

3. **No automatic fallback between backends.** A silent fall-through from a local backend to a billed one is how a cost optimisation becomes a cost surprise, and it hides a broken local backend behind an invoice. No safety net is needed in-repo: a failed call already skips the session and writes the deterministic slim handoff.

4. **Secrets are named, never carried.** `api_key_env` reuses the `url_env` mechanism in `monitoring/sink_setup.py` verbatim — resolved at call time so the value never reaches disk, owner-only secrets-file fallback, and the parser rejects the literal and the variable together. This matters because `config.toml` is a chezmoi `.tmpl`.

5. **Backwards compatible.** `[compound_loop].backend`/`.model` map to a synthetic `distill` role with a one-time warning. ADR-033's fields are deprecated, not removed.

6. **The tool tri-state survives `--role`, and exit codes stay parseable.** `--allow-tools` on an inference backend is a hard error — it requests a capability that does not exist. `--no-tools` is an accepted no-op, because it asserts a truth that already holds; rejecting it would force every consumer to branch its tri-state on whether a role was passed, restoring the coupling the role removes. And exit code `2` is never emitted for a failed inference: it stays the usage-error code, raised before any inference runs and carrying no envelope. A consumer branching on the process exit before parsing stdout therefore never discards a failure whose cause is in `error.kind`.

Because the motivating consumer lives in another repository, `lh exec --role <name> --dry-run` and a `lh doctor` check over the whole role table are part of this decision, not follow-up polish. Without them a role could be broken with the suite green — the "implemented but never wired" failure this repo has recorded before.

## Alternatives considered

- **Register Ollama as an `AgentAdapter`.** Rejected. `AgentAdapter` is subprocess-shaped throughout — `resolve_binary`, `process_name`, `headless_argv`, `session_argv`, process-group teardown, transcript billing. An HTTP endpoint satisfies none of it, so the adapter returns `None`/`[]` across half the Protocol: `NullAdapter` in production. And `[agent].type` is global, so setting it would also change what `lh run` launches interactively.

- **Keep two doors and document the split.** Rejected, though genuinely defensible — agentic execution and single-turn inference are different things. What decided it: the split as drawn forces the cost-accounting machinery to be written twice, and one copy is already missing. A seam whose duplication cost is a live observability gap is cut in the wrong place.

- **A router that picks the best model automatically.** Deferred, explicitly. It needs a per-role quality signal that does not exist; without one it is a hunch with more code. The inputs for a future attempt already exist (ADR-021 grading, ADR-037 workload attribution) and are deliberately unused here.

- **A second agent adapter (Codex, Gemini CLI) in the same change.** Out of scope. That is the *agent* axis behind ADR-004/ADR-032. This decision makes the *inference* axis pluggable; it neither delivers nor blocks the other.

## Consequences

**Positive**

- One implementation of each provider call, instead of two that drift.
- Compound-loop spend becomes visible in `metrics.db` for the first time, through machinery that already exists.
- A caller outside this repository can request local inference against a versioned contract, without importing `lazy_harness`.
- Per-role routing makes "classify locally, distil with Claude" expressible, which the single global backend value could not express.
- OpenRouter and any other OpenAI-compatible provider become usable without a plaintext key in a chezmoi-managed file.

**Negative**

- The `lh.exec/v1` envelope grows a field and gains more structural nulls on the inference path. Mitigated by `mode`, but consumers must read it.
- Two config shapes coexist during deprecation, and the loader has to reconcile them with a documented precedence.
- `run_inference` never raising means a caller that ignores `success` silently processes an empty string. The in-repo callers are migrated with the change; external ones are covered by the contract section of the design.
- A role table is more configuration surface than one `backend` key, and a role naming an undefined backend is a new class of misconfiguration. This is what the `lh doctor` check exists to catch.
