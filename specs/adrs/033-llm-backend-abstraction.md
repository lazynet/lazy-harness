# ADR-033: LLM backend abstraction — provider-agnostic inference

**Status:** accepted
**Date:** 2026-05-27
**Implemented:** 2026-06-11 — `src/lazy_harness/llm/` (Protocol, ClaudeBackend, OpenAICompatibleBackend, registry), config fields, worker/CLI wiring, `lh doctor` check.
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent-adapter-pattern), ADR-008 (compound-loop-async-worker),
ADR-021 (async-response-grading), ADR-032 (agent-adapter-completeness)

## Context

The `AgentAdapter` Protocol (ADR-004) abstracts the *agent CLI* — the process
that the developer talks to and whose lifecycle the framework manages. It does
not abstract the *LLM* that actually generates tokens.

Today the framework couples two distinct concepts:

1. **Claude Code** as the agent CLI (hooks, config, binary path).
2. **Claude API** as the inference backend used by the framework itself to
   process session transcripts (compound-loop, response grading, memory
   consolidation).

The coupling manifests as:

- `compound_loop.py` calls `subprocess.run(["claude", "-p", ...])` — the same
  binary the user talks to — to run headless inference.
- `memory_cmd.py` imports `invoke_claude` and defaults the model to
  `claude-haiku-4-5-20251001`.
- `CompoundLoopConfig.model` defaults to `claude-haiku-4-5-20251001`.
- All three locations assume the Claude binary is present and that the user
  has an Anthropic API key.

This coupling has two failure modes:

**A — Agent ≠ inference provider.** A user running Gemini CLI as their agent
(ADR-031) still needs the Claude binary installed just for the framework's
internal inference calls. The coupling forces an unnecessary dependency on a
CLI the user has replaced.

**B — Local inference.** Users running models via Ollama or Apple MLX serve
an OpenAI-compatible HTTP API locally. They may prefer or require that the
framework's inference calls stay local (cost, privacy, offline operation).
Today there is no mechanism for this without patching the source.

The resolution is a `LLMBackend` Protocol — structurally parallel to
`AgentAdapter` — that isolates the "how the framework calls a model" decision
from the "which agent the user runs" decision.

## Decision

Introduce a `LLMBackend` Protocol at `src/lazy_harness/llm/base.py` and a
registry at `src/lazy_harness/llm/registry.py`. All framework-internal LLM
calls go through the active backend. The active backend is resolved from
`[compound_loop].backend` in `config.toml`.

### Protocol definition

```python
# src/lazy_harness/llm/base.py

from typing import Protocol, runtime_checkable

@runtime_checkable
class LLMBackend(Protocol):
    @property
    def name(self) -> str:
        """Unique identifier, matches the config.toml value."""
        ...

    def default_model(self) -> str:
        """Model identifier to use when the config does not specify one."""
        ...

    def complete(self, prompt: str, model: str, timeout: int) -> str:
        """Run a single-turn completion and return the response text.

        Raises `LLMBackendError` on any failure (connection, timeout,
        content refusal). The caller is responsible for retry logic.
        """
        ...
```

The Protocol is intentionally minimal. The framework's inference calls are
all single-turn (prompt → text); streaming, tool use, and multi-turn context
are not needed here.

### Implementations

**`ClaudeBackend`** (`src/lazy_harness/llm/claude.py`)

Wraps the existing `subprocess.run(["claude", "-p", ...])` call. Identical
behaviour to today; zero regression for existing users. Requires `claude` on
PATH. Default model: `claude-haiku-4-5-20251001`.

```python
class ClaudeBackend:
    @property
    def name(self) -> str:
        return "claude"

    def default_model(self) -> str:
        return "claude-haiku-4-5-20251001"

    def complete(self, prompt: str, model: str, timeout: int) -> str:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", model],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            raise LLMBackendError(result.stderr)
        return result.stdout.strip()
```

**`OpenAICompatibleBackend`** (`src/lazy_harness/llm/openai_compat.py`)

Calls any OpenAI-compatible `/v1/chat/completions` endpoint using `httpx`
(already in the dependency tree via indirect dependencies; add explicitly if
not). Covers Ollama, Apple MLX serve, LM Studio, OpenRouter, and any other
provider exposing the OpenAI wire format.

```python
class OpenAICompatibleBackend:
    def __init__(self, base_url: str, api_key: str = "none", **kwargs):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "openai-compatible"

    def default_model(self) -> str:
        return "llama3.2:3b"   # sensible Ollama default; override in config

    def complete(self, prompt: str, model: str, timeout: int) -> str:
        import httpx
        resp = httpx.post(
            f"{self._base_url}/v1/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": prompt}]},
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
```

Named aliases `"ollama"` and `"mlx"` registered in the registry map to
`OpenAICompatibleBackend` with pre-set `base_url` defaults:

| Alias | `base_url` default |
|-------|--------------------|
| `claude` | — (subprocess, no URL) |
| `openai-compatible` | user-supplied via `backend_options.base_url` |
| `ollama` | `http://localhost:11434` |
| `mlx` | `http://localhost:8080` |

The alias approach keeps config.toml simple for the common case
(`backend = "ollama"`) while preserving full control for custom deployments
(`backend = "openai-compatible"`, `base_url = "http://my-gpu-box:11434"`).

### Config changes

```toml
[compound_loop]
backend = "claude"                    # default, unchanged behaviour
model   = "claude-haiku-4-5-20251001" # default, unchanged

# Opt into Ollama — only these two lines change:
# backend = "ollama"
# model   = "llama3.2:3b"

# Custom OpenAI-compatible endpoint:
# backend = "openai-compatible"
# model   = "mistral-nemo"
# [compound_loop.backend_options]
# base_url = "http://my-gpu-box:11434"
# api_key  = "sk-..."
```

New `CompoundLoopConfig` fields:

```python
@dataclass
class CompoundLoopConfig:
    # ... existing fields unchanged ...
    backend: str = "claude"
    backend_options: dict[str, str] = field(default_factory=dict)
```

### Registry and resolution

```python
# src/lazy_harness/llm/registry.py

def get_backend(cfg: CompoundLoopConfig) -> LLMBackend:
    """Instantiate the configured LLM backend."""
    name = cfg.backend
    options = cfg.backend_options

    if name == "claude":
        return ClaudeBackend()
    if name in ("ollama", "mlx", "openai-compatible"):
        base_url = options.get("base_url") or _DEFAULT_URLS[name]
        api_key  = options.get("api_key", "none")
        return OpenAICompatibleBackend(base_url=base_url, api_key=api_key)

    raise LLMBackendNotFoundError(
        f"LLM backend '{name}' not found. Available: claude, ollama, mlx, openai-compatible"
    )
```

`invoke_claude` in `knowledge/compound_loop.py` is renamed `invoke_llm` and
its signature becomes:

```python
def invoke_llm(
    prompt: str,
    backend: LLMBackend,
    model: str,
    timeout: int,
) -> str:
```

Callers pass the backend instance (obtained from `get_backend(cfg.compound_loop)`
at startup) rather than calling `invoke_claude` by name. The subprocess-specific
logic moves into `ClaudeBackend.complete`.

### Separation from agent selection

The two configs are deliberately orthogonal:

```toml
[agent]
type = "gemini-cli"      # which agent the user runs

[compound_loop]
backend = "ollama"       # which LLM the framework uses internally
model   = "llama3.2:3b"
```

A user running Gemini CLI with Ollama for internal inference is fully supported
with no awkward coupling. A user running Claude Code who wants local inference
can flip only `backend` without changing their agent config.

## Alternatives considered

- **Extend the `AgentAdapter` Protocol to include inference.** Rejected. The
  agent (the CLI tool) and the LLM backend are independent choices. Coupling
  them would force a Gemini CLI adapter to also specify inference behaviour
  even when the user wants Ollama. The Protocol boundary must match the
  conceptual boundary.

- **Use the Anthropic Python SDK instead of subprocess for `ClaudeBackend`.**
  Considered as an improvement for `ClaudeBackend`. Deferred. The subprocess
  approach works today and adding `anthropic` as a hard dependency for what is
  already an optional feature (compound-loop is off by default) does not
  pay off yet. If the SDK approach brings value (streaming, cost metrics,
  caching), it can replace the subprocess implementation in `ClaudeBackend`
  without changing the Protocol or any caller.

- **Hardcode Ollama/MLX support as special cases in `compound_loop.py`.** Rejected.
  Two `if backend == "ollama":` branches in `compound_loop.py` is the same
  mistake as the Claude leaks ADR-031 is fixing in the agent layer. The
  Protocol prevents accumulation of per-provider branches in non-provider code.

- **LangChain / LiteLLM as the abstraction layer.** Rejected. Both are
  large dependencies with their own opinions about prompt formatting,
  retry logic, and output parsing. The framework's inference calls are a
  narrow use case (one prompt in, one text string out); a two-method Protocol
  is the minimum sufficient abstraction, and minimum is right here.

- **One `LLMBackend` per named model (Claude-Haiku, Llama-3.2-3b, etc.).**
  Rejected. The model selection is a runtime concern (one config value), not
  an architectural boundary. The backend knows *how* to call a provider;
  the model is *which* checkpoint to use. They vary independently.

- **Expose `LLMBackend` as a public API for users to implement.** Deferred.
  Today the backends are internal. If a use case arises for plugin-style
  backends (e.g., an Azure OpenAI adapter with custom auth), the registry can
  gain an entry-point discovery path — the same "defer the plugin system until
  we have more than one implementation" reasoning as ADR-004.

## Consequences

**Positive**

- A user can run the framework's compound-loop entirely locally (Ollama/MLX)
  with zero cloud API keys. Cost goes to zero for internal inference; privacy
  is preserved for users who cannot send transcript data to a cloud API.
- Agent choice and inference backend are decoupled. Switching from Claude Code
  to another agent does not force a change to the inference config, and vice
  versa.
- `ClaudeBackend` preserves exact parity with today's behaviour. No regression
  risk for existing users.
- The `openai-compatible` backend covers every current local provider
  (Ollama, MLX serve, LM Studio) and many cloud providers (OpenRouter,
  Together, Fireworks) with a single implementation.
- `invoke_llm` is now unit-testable: tests pass a stub backend instead of
  mocking a subprocess.

**Negative**

- `httpx` becomes an explicit runtime dependency (currently implicit). Small.
- Two new config fields (`backend`, `backend_options`) expand the
  `[compound_loop]` table. Mitigated by the existing `lh config compound-loop
  --init` wizard path (ADR-026).
- The rename `invoke_claude` → `invoke_llm` touches callers in
  `knowledge/compound_loop.py` and `cli/memory_cmd.py`. Mechanical change.
- Model quality varies significantly across providers. A user switching to a
  small local model for compound-loop inference may get lower-quality
  decisions/learnings output. The framework cannot guard against this; it is
  a user-acknowledged trade-off.
- `ClaudeBackend` requires the `claude` binary at runtime. If the user is
  running a different agent CLI and has not installed Claude Code, they must
  set `backend` explicitly. The default remains `"claude"` to preserve zero
  regression; an explicit error message guides the fix.

## Implementation

Recommended sequence (each step independently shippable):

1. Add `src/lazy_harness/llm/base.py` with the Protocol and `LLMBackendError`.
2. Add `src/lazy_harness/llm/claude.py` — extract the subprocess call from
   `compound_loop.py` verbatim. All existing tests pass unchanged.
3. Rename `invoke_claude` → `invoke_llm` in `compound_loop.py`; thread the
   `backend: LLMBackend` parameter through.
4. Add `CompoundLoopConfig.backend` and `backend_options` to `core/config.py`;
   default to `"claude"`. Update `lh config compound-loop --init` wizard.
5. Add `src/lazy_harness/llm/openai_compat.py` with `OpenAICompatibleBackend`.
6. Add `src/lazy_harness/llm/registry.py` with aliases table.
7. Wire `get_backend(cfg.compound_loop)` into `cli/memory_cmd.py` and the
   compound-loop worker startup.
8. Add `lh doctor` detection for the configured backend (is Ollama reachable?
   is the `claude` binary present? Following ADR-025 patterns).

Step 2 is the safety checkpoint: if it passes `lh selftest` with identical
behaviour, steps 3–8 are mechanical plumbing with no logic changes.
