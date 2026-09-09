# Role-Routed Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `lh exec` the single seam through which every model call resolves, with a named role choosing the backend, so local models can serve cheap work while Claude keeps the work that needs it.

**Architecture:** A new `[llm]` config table maps roles to named backends. `llm/invoke.py::run_inference` is the one place that resolves a role, executes, and maps failures to typed kinds; it never raises. `lh exec --role` and the in-repo callers are two front ends over it. ADR-033's registry and backends are reused, not replaced.

**Tech Stack:** Python 3.11+, `uv`, `pytest`, `ruff`, `click`, `httpx`, MkDocs Material.

**Spec:** [`specs/designs/2026-09-09-llm-role-routing-design.md`](../designs/2026-09-09-llm-role-routing-design.md) and [`ADR-039`](../adrs/039-role-routed-inference.md)

## Global Constraints

- **Strict TDD, no exceptions.** No production line is written before a failing test that exercises it. Follow `superpowers:test-driven-development`.
- **Conventional commits, no AI trailers.** `type: short description`. Never `--no-verify`.
- **Every commit passes all three:** `uv run pytest`, `uv run ruff check src tests`, `uv run --group docs mkdocs build --strict`.
- **Never hand-bump versions.** release-please owns `pyproject.toml` and `__init__.py`.
- **Run every command from the worktree** `.worktrees/llm-role-routing`, via `uv run --directory <worktree>` or with the worktree as cwd. Never against a live profile.
- **Backward compatibility is absolute:** a config with only `[compound_loop].backend` keeps working, and an agent-mode envelope stays field-for-field identical.
- Exit codes: `0` success, `124` timeout, `70` any other failed inference, `2` reserved for usage errors that carry no envelope.
- The five inference kinds are exhaustive: `backend-unreachable`, `timeout`, `schema-violation`, `empty`, `backend-error`.

## File Structure

| File | Responsibility |
|---|---|
| `src/lazy_harness/core/config.py` | `LLMConfig`, `LLMBackendConfig`, parse, serialise, deprecation bridge |
| `src/lazy_harness/llm/roles.py` | **create** — role → backend resolution, the single deciding rule |
| `src/lazy_harness/llm/invoke.py` | **create** — `run_inference`, `InferenceResult`, `InferenceError` |
| `src/lazy_harness/llm/base.py` | `schema` keyword on the Protocol |
| `src/lazy_harness/llm/openai_compat.py` | `response_format` pass-through |
| `src/lazy_harness/llm/claude.py` | accept and ignore `schema` |
| `src/lazy_harness/cli/exec_cmd.py` | `--role`, `mode`, exit mapping, inference dry-run |
| `src/lazy_harness/cli/doctor_cmd.py` | validate the whole role table |
| `src/lazy_harness/plugins/builtins.py` | capability `config_path` moves to `llm.roles` |
| `src/lazy_harness/knowledge/compound_loop.py` | `invoke_llm` deleted, calls `run_inference` |
| `src/lazy_harness/knowledge/compound_loop_worker.py` | role resolution instead of `get_backend` |
| `src/lazy_harness/cli/memory_cmd.py` | `_resolve_backend_and_model` deleted |
| `docs/reference/config.md`, `docs/reference/cli.md` | user-facing docs |

`roles.py` is separate from `registry.py` on purpose: the registry answers "how do I call this provider", the roles module answers "who should answer this call". Keeping the deciding rule in one importable place is what lets the capability registry and `run_inference` be tested for agreement.

---

### Task 1: `[llm]` config table

**Files:**
- Modify: `src/lazy_harness/core/config.py` (dataclasses near `CompoundLoopConfig:196`, parse near `:545`, `Config:260`)
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: nothing
- Produces: `LLMBackendConfig(type: str, model: str, base_url: str, api_key: str, api_key_env: str)`, `LLMConfig(default_role: str, backends: dict[str, LLMBackendConfig], roles: dict[str, str])`, `Config.llm: LLMConfig`

- [ ] **Step 1: Write the failing tests**

```python
def test_llm_table_parses_backends_and_roles(config_dir: Path) -> None:
    cfg_file = config_dir / "config.toml"
    cfg_file.write_text(
        """
[llm]
default_role = "distill"

[llm.backends.local]
type = "ollama"
model = "qwen2.5-coder:7b"

[llm.roles]
classify = "local"
"""
    )
    cfg = load_config(cfg_file)
    assert cfg.llm.default_role == "distill"
    assert cfg.llm.backends["local"].type == "ollama"
    assert cfg.llm.backends["local"].model == "qwen2.5-coder:7b"
    assert cfg.llm.roles["classify"] == "local"


def test_llm_defaults_when_section_absent() -> None:
    assert LLMConfig().backends == {}
    assert LLMConfig().roles == {}


def test_llm_backend_rejects_api_key_and_api_key_env_together(config_dir: Path) -> None:
    cfg_file = config_dir / "config.toml"
    cfg_file.write_text(
        """
[llm.backends.remote]
type = "openai-compatible"
base_url = "https://example.invalid/v1"
api_key = "sk-literal"
api_key_env = "SOME_VAR"
"""
    )
    with pytest.raises(ConfigError, match="api_key_env"):
        load_config(cfg_file)


def test_llm_roles_must_be_a_table(config_dir: Path) -> None:
    cfg_file = config_dir / "config.toml"
    cfg_file.write_text('[llm]\nroles = "not-a-table"\n')
    with pytest.raises(ConfigError, match="llm.roles"):
        load_config(cfg_file)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -k llm -v`
Expected: FAIL — `LLMConfig` is not defined.

- [ ] **Step 3: Implement**

Add beside `CompoundLoopConfig`:

```python
@dataclass
class LLMBackendConfig:
    type: str = "claude"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    #: Names the environment variable holding the key. Never the value —
    #: config.toml is a chezmoi template, so a literal lands in dotfiles.
    api_key_env: str = ""


@dataclass
class LLMConfig:
    default_role: str = ""
    backends: dict[str, LLMBackendConfig] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
```

Add `llm: LLMConfig = field(default_factory=LLMConfig)` to `Config`. Add a `_parse_llm(raw)` helper that raises `ConfigError` naming `llm.backends.<name>: api_key and api_key_env are mutually exclusive` and `[llm].roles must be a table`, and call it from `load_config`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_config.py -k llm -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/core/config.py tests/unit/test_config.py
git commit -m "feat: add [llm] config table with backends and roles"
```

---

### Task 2: Role resolution and the deprecation bridge

**Files:**
- Create: `src/lazy_harness/llm/roles.py`
- Test: `tests/unit/llm/test_roles.py`

**Interfaces:**
- Consumes: `LLMConfig`, `CompoundLoopConfig`, `Config` from Task 1
- Produces: `resolve_role(cfg: Config, role: str) -> ResolvedRole`, `ResolvedRole(role, backend_name, type, model, base_url, api_key_env)`, `RoleNotFoundError`, `DEPRECATED_ROLE = "distill"`

- [ ] **Step 1: Write the failing tests**

```python
def test_resolves_role_to_its_backend() -> None:
    cfg = Config()
    cfg.llm = LLMConfig(
        backends={"local": LLMBackendConfig(type="ollama", model="qwen2.5-coder:7b")},
        roles={"classify": "local"},
    )
    resolved = resolve_role(cfg, "classify")
    assert resolved.type == "ollama"
    assert resolved.model == "qwen2.5-coder:7b"


def test_role_naming_undefined_backend_is_an_error() -> None:
    cfg = Config()
    cfg.llm = LLMConfig(roles={"classify": "ghost"})
    with pytest.raises(RoleNotFoundError, match="ghost"):
        resolve_role(cfg, "classify")


def test_compound_loop_backend_maps_to_synthetic_distill_role() -> None:
    """The ADR-033 form keeps working with no [llm] table at all."""
    cfg = Config()
    cfg.compound_loop.backend = "ollama"
    cfg.compound_loop.model = "llama3.2:3b"
    resolved = resolve_role(cfg, "distill")
    assert resolved.type == "ollama"
    assert resolved.model == "llama3.2:3b"


def test_llm_table_wins_over_deprecated_compound_loop_fields() -> None:
    cfg = Config()
    cfg.compound_loop.backend = "ollama"
    cfg.llm = LLMConfig(
        backends={"h": LLMBackendConfig(type="claude", model="claude-haiku-4-5-20251001")},
        roles={"distill": "h"},
    )
    assert resolve_role(cfg, "distill").type == "claude"


def test_deprecated_form_warns_once(recwarn) -> None:
    cfg = Config()
    cfg.compound_loop.backend = "ollama"
    resolve_role(cfg, "distill")
    resolve_role(cfg, "distill")
    assert len([w for w in recwarn if "compound_loop" in str(w.message)]) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/llm/test_roles.py -v` → FAIL, module missing.

- [ ] **Step 3: Implement**

`resolve_role` checks `cfg.llm.roles` first; on a miss for the name `distill` it falls back to `cfg.compound_loop.backend`/`.model`, emitting a `DeprecationWarning` guarded by a module-level flag so it fires once per process. Unknown backend name raises `RoleNotFoundError`. Unknown role with no fallback raises `RoleNotFoundError` listing the defined roles.

- [ ] **Step 4: Run to verify they pass** → PASS

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/llm/roles.py tests/unit/llm/test_roles.py
git commit -m "feat: resolve inference roles with a compound_loop deprecation bridge"
```

---

### Task 3: Config serialisation and round trip

**Files:**
- Modify: `src/lazy_harness/core/config.py:675-690` (the `save_config` dict)
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: Task 1 dataclasses
- Produces: `[llm]` present in `save_config` output

- [ ] **Step 1: Write the failing tests**

```python
def test_llm_table_round_trips(config_dir: Path) -> None:
    """save → load → save → load is stable. Validation checks schema, not
    parsability, so a section with defaults needs the full cycle."""
    cfg = Config()
    cfg.llm = LLMConfig(
        default_role="distill",
        backends={"local": LLMBackendConfig(type="ollama", model="qwen2.5-coder:7b")},
        roles={"classify": "local"},
    )
    p = config_dir / "config.toml"
    save_config(cfg, p)
    once = load_config(p)
    save_config(once, p)
    twice = load_config(p)
    assert twice.llm == once.llm == cfg.llm


def test_llm_survives_merge_onto_existing_document(config_dir: Path) -> None:
    p = config_dir / "config.toml"
    p.write_text('[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n')
    cfg = load_config(p)
    cfg.llm = LLMConfig(backends={"local": LLMBackendConfig(type="ollama")}, roles={"c": "local"})
    save_config(cfg, p)
    assert load_config(p).llm.roles == {"c": "local"}
    assert load_config(p).agent.type == "claude-code"


def test_api_key_env_is_serialised_but_never_a_literal_key(config_dir: Path) -> None:
    cfg = Config()
    cfg.llm = LLMConfig(
        backends={"r": LLMBackendConfig(type="openai-compatible", api_key_env="SOME_VAR")}
    )
    p = config_dir / "config.toml"
    save_config(cfg, p)
    assert "SOME_VAR" in p.read_text()
    assert "api_key =" not in p.read_text()
```

- [ ] **Step 2: Run to verify they fail** → FAIL, `[llm]` absent from output.

- [ ] **Step 3: Implement** — add the `"llm"` block to the `save_config` dict, omitting empty string fields so a default document stays clean.

- [ ] **Step 4: Run to verify they pass** → PASS

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/core/config.py tests/unit/test_config.py
git commit -m "feat: serialise the [llm] table with a stable round trip"
```

---

### Task 4: `schema` on the LLMBackend Protocol

**Files:**
- Modify: `src/lazy_harness/llm/base.py`, `src/lazy_harness/llm/claude.py`, `src/lazy_harness/llm/openai_compat.py`
- Test: `tests/unit/llm/test_openai_compat.py`, `tests/unit/llm/test_claude.py`, `tests/unit/llm/test_base.py`

**Interfaces:**
- Produces: `complete(prompt, model, timeout, *, schema: dict | None = None) -> str` on every backend

- [ ] **Step 1: Write the failing tests**

```python
def test_schema_becomes_response_format(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, json, headers, timeout):
        captured.update(json)
        return _resp({"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    schema = {"type": "object", "properties": {"kind": {"type": "string"}}}
    OpenAICompatibleBackend(base_url="http://x").complete("p", "m", 5, schema=schema)
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["schema"] == schema


def test_no_schema_sends_no_response_format(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, json, headers, timeout):
        captured.update(json)
        return _resp({"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    OpenAICompatibleBackend(base_url="http://x").complete("p", "m", 5)
    assert "response_format" not in captured


def test_claude_accepts_and_ignores_schema(monkeypatch) -> None:
    """claude -p has no equivalent flag; the argv must not grow one."""
    captured: dict = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ClaudeBackend().complete("p", "m", 5, schema={"type": "object"})
    assert "--response-format" not in captured["argv"]
    assert "schema" not in " ".join(captured["argv"])
```

- [ ] **Step 2: Run to verify they fail** → FAIL, `complete()` takes no `schema`.

- [ ] **Step 3: Implement** — add the keyword to the Protocol and both backends; `OpenAICompatibleBackend` adds `response_format` only when `schema` is not None.

- [ ] **Step 4: Run to verify they pass** → PASS

- [ ] **Step 5: Prove the guard guards**

Delete the `response_format` line by hand, run the suite, confirm `test_schema_becomes_response_format` fails, then restore **by editing the file back by hand** — never `git checkout`, which would revert the uncommitted implementation too.

- [ ] **Step 6: Commit**

```bash
git add src/lazy_harness/llm tests/unit/llm
git commit -m "feat: pass a JSON schema through to OpenAI-compatible backends"
```

---

### Task 5: The `run_inference` seam

**Files:**
- Create: `src/lazy_harness/llm/invoke.py`
- Test: `tests/unit/llm/test_invoke.py`

**Interfaces:**
- Consumes: `resolve_role` (Task 2), `get_backend` (`llm/registry.py`), `complete(..., schema=)` (Task 4)
- Produces: `run_inference(prompt, *, role, cfg, timeout, schema=None) -> InferenceResult`; `InferenceResult(output: str, success: bool, model: str, backend: str, duration_ms: int, error: InferenceError | None)`; `InferenceError(kind: str, message: str)`; `INFERENCE_KINDS: tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

```python
def test_success_returns_output_and_no_error() -> None:
    cfg = _cfg_with_stub("ok")
    r = run_inference("p", role="classify", cfg=cfg, timeout=5)
    assert r.success is True
    assert r.output == "ok"
    assert r.error is None


def test_never_raises_on_backend_error() -> None:
    cfg = _cfg_with_stub(raises=LLMBackendError("connection refused"))
    r = run_inference("p", role="classify", cfg=cfg, timeout=5)
    assert r.success is False
    assert r.error.kind == "backend-unreachable"


def test_empty_output_is_its_own_kind() -> None:
    r = run_inference("p", role="classify", cfg=_cfg_with_stub(""), timeout=5)
    assert r.error.kind == "empty"
    assert r.output == ""


def test_schema_violation_when_output_does_not_validate() -> None:
    schema = {"type": "object", "required": ["kind"]}
    r = run_inference("p", role="classify", cfg=_cfg_with_stub('{"other": 1}'),
                      timeout=5, schema=schema)
    assert r.error.kind == "schema-violation"


def test_output_is_a_string_on_every_failure_kind() -> None:
    for cfg in _cfgs_for_every_failure_kind():
        r = run_inference("p", role="classify", cfg=cfg, timeout=5)
        assert isinstance(r.output, str)


def test_unknown_role_is_reported_not_raised() -> None:
    r = run_inference("p", role="nope", cfg=Config(), timeout=5)
    assert r.success is False
    assert r.error.kind == "backend-unreachable"


def test_kinds_are_exhaustive() -> None:
    assert INFERENCE_KINDS == (
        "backend-unreachable", "timeout", "schema-violation", "empty", "backend-error",
    )


def test_a_failing_local_role_never_falls_back_to_another_backend() -> None:
    """§6 of the design. A silent fall-through to a billed model is how a cost
    optimisation becomes a cost surprise, so assert the second backend is
    never constructed — not merely that the result reports failure."""
    built: list[str] = []
    cfg = _cfg_with_two_backends(local_raises=True, on_build=built.append)
    r = run_inference("p", role="classify", cfg=cfg, timeout=5)
    assert r.success is False
    assert built == ["ollama"]
```

- [ ] **Step 2: Run to verify they fail** → FAIL, module missing.

- [ ] **Step 3: Implement** — resolve the role, build the backend via `get_backend`, time the call with `time.perf_counter`, catch `LLMBackendError`/`RoleNotFoundError`/timeout and map to kinds.

Validation is a **local `_validate(payload, schema)` of about twenty lines — no new dependency.** `pyproject.toml` carries five runtime deps (`click`, `httpx`, `rich`, `tomli-w`, `tomlkit`); adding `jsonschema` for a required-keys-and-enums check is the same trade ADR-033 refused when it rejected LiteLLM. Check exactly three things, which is what the measured failure mode needs:

```python
def _validate(payload: object, schema: dict) -> str:
    """Return "" when valid, else a reason. Not a JSON Schema implementation:
    it checks the three properties the backend was asked to enforce, so a
    backend that ignored the request is caught rather than trusted."""
    if schema.get("type") == "object" and not isinstance(payload, dict):
        return f"expected an object, got {type(payload).__name__}"
    if not isinstance(payload, dict):
        return ""
    for key in schema.get("required", []):
        if key not in payload:
            return f"missing required key {key!r}"
    for key, spec in schema.get("properties", {}).items():
        allowed = spec.get("enum") if isinstance(spec, dict) else None
        if allowed and key in payload and payload[key] not in allowed:
            return f"{key}={payload[key]!r} is outside {allowed!r}"
    return ""
```

The enum branch is the one that earns its place: the design measured `qwen2.5-coder:7b` answering `"bug"` against an enum of `debug|feature|docs|other`.

- [ ] **Step 4: Run to verify they pass** → PASS

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/llm/invoke.py tests/unit/llm/test_invoke.py
git commit -m "feat: add run_inference, the single inference resolution seam"
```

---

### Task 6: Migrate the in-repo callers

**Files:**
- Modify: `src/lazy_harness/knowledge/compound_loop.py:857,1220,1275`, `src/lazy_harness/knowledge/compound_loop_worker.py:25,68,132`, `src/lazy_harness/cli/memory_cmd.py:21-50,185`
- Test: `tests/unit/test_compound_loop.py`, `tests/unit/cli/test_memory_cmd.py`, `tests/unit/test_compound_loop_worker.py`

**Interfaces:**
- Consumes: `run_inference` (Task 5)
- Produces: `invoke_llm` no longer exists; `process_task` takes `cfg: Config` rather than a prebuilt backend

- [ ] **Step 1: Write the failing tests**

```python
def test_process_task_uses_the_distill_role(monkeypatch, tmp_path) -> None:
    seen: dict = {}

    def fake_run_inference(prompt, *, role, cfg, timeout, schema=None):
        seen["role"] = role
        return InferenceResult(output="{}", success=True, model="m",
                               backend="stub", duration_ms=1, error=None)

    monkeypatch.setattr(mod, "run_inference", fake_run_inference)
    process_task(task_file, cfg, learnings_dir)
    assert seen["role"] == "distill"


def test_failed_inference_still_writes_the_slim_handoff(monkeypatch, tmp_path) -> None:
    """The existing degradation path must survive the migration."""
    monkeypatch.setattr(mod, "run_inference", _always_fails)
    outcome = process_task(task_file, cfg, learnings_dir)
    assert outcome.skipped
    assert (memory_dir / "handoff.md").exists()


def test_invoke_llm_is_gone() -> None:
    import lazy_harness.knowledge.compound_loop as cl
    assert not hasattr(cl, "invoke_llm")
```

- [ ] **Step 2: Run to verify they fail** → FAIL.

- [ ] **Step 3: Implement** — thread `cfg` through, delete `invoke_llm`, delete `_resolve_backend_and_model`, update the tests that monkeypatched `_invoke_llm` to patch `run_inference` instead.

- [ ] **Step 4: Run the whole suite** — `uv run pytest` must be fully green; this task touches the most existing tests.

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness tests
git commit -m "refactor: route in-repo inference through run_inference"
```

---

### Task 7: `lh exec --role`

**Files:**
- Modify: `src/lazy_harness/cli/exec_cmd.py`
- Test: `tests/unit/cli/test_exec_cmd.py`

**Interfaces:**
- Consumes: `run_inference` (Task 5)
- Produces: `--role` option; envelope key `mode`

- [ ] **Step 1: Write the failing tests**

```python
def test_agent_envelope_is_field_for_field_unchanged_except_mode() -> None:
    """The lh.exec/v1 compatibility invariant, asserted directly."""
    before = set(_ENVELOPE_KEYS_BEFORE_THIS_CHANGE)
    after = set(json.loads(_run_agent_dry_run().output))
    assert after - before == {"mode"}
    assert before - after == set()


def test_inference_envelope_declares_its_mode() -> None:
    env = _run(["--role", "classify"], stdin="hi")
    assert env["mode"] == "inference"
    assert env["num_turns"] is None


def test_output_is_never_null_on_failure() -> None:
    env = _run(["--role", "unreachable-role"], stdin="hi")
    assert env["output"] == ""
    assert env["error"]["kind"] in INFERENCE_KINDS


def test_timeout_exits_124_and_other_failures_exit_70() -> None:
    assert _exit_for_kind("timeout") == 124
    for kind in ("backend-unreachable", "schema-violation", "empty", "backend-error"):
        assert _exit_for_kind(kind) == 70


def test_no_failed_inference_exits_2() -> None:
    for kind in INFERENCE_KINDS:
        assert _exit_for_kind(kind) != 2


def test_no_tools_with_role_is_an_accepted_no_op() -> None:
    env = _run(["--role", "classify", "--no-tools"], stdin="hi")
    assert env["mode"] == "inference"
    assert env["error"] is None


def test_allow_tools_with_role_is_a_usage_error() -> None:
    result = _invoke(["--role", "classify", "--allow-tools", "Read"], stdin="hi")
    assert result.exit_code == 2


def test_tier_and_model_are_rejected_with_role() -> None:
    assert _invoke(["--role", "c", "--tier", "fast"]).exit_code == 2
    assert _invoke(["--role", "c", "--model", "x"]).exit_code == 2


def test_dry_run_emits_the_same_shape_with_the_plan(monkeypatch) -> None:
    monkeypatch.setenv("SOME_VAR", "sk-secret")
    env = _run(["--role", "classify", "--dry-run"])
    assert env["dry_run"] is True and env["success"] is True
    assert env["exit_code"] == 0 and env["output"] == "" and env["error"] is None
    assert env["harness"]["backend"] == "ollama"
    assert "sk-secret" not in json.dumps(env)
```

- [ ] **Step 2: Run to verify they fail** → FAIL, `--role` unknown.

- [ ] **Step 3: Implement** — add the option, the mutual-exclusion checks (`--tier`, `--model`, `--allow-tools`), `mode` in `_base_envelope`, the exit mapping, and the inference dry-run plan in the `harness` block.

- [ ] **Step 4: Run to verify they pass** → PASS

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/cli/exec_cmd.py tests/unit/cli/test_exec_cmd.py
git commit -m "feat: add lh exec --role for inference-mode runs"
```

---

### Task 8: Move the capability registry entry

**Files:**
- Modify: `src/lazy_harness/plugins/builtins.py:143-152`
- Test: `tests/plugins/test_capabilities.py`

**Interfaces:**
- Consumes: `resolve_role` (Task 2), `run_inference` (Task 5)
- Produces: capability `config_path` pointing at the live table

- [ ] **Step 1: Write the failing tests**

```python
def test_registry_and_run_inference_agree_on_the_active_backend() -> None:
    """Two code paths answering the same question, asserted against one config."""
    for cfg in (_cfg_deprecated_form(), _cfg_llm_table_form()):
        from_registry = builtin_registry().active_llm_backend(cfg)
        from_seam = resolve_role(cfg, "distill").type
        assert from_registry == from_seam


def test_capability_config_path_is_not_the_deprecated_field() -> None:
    caps = [c for c in builtin_registry().all() if c.kind == "llm_backend"]
    assert caps
    assert all(c.config_path != "compound_loop.backend" for c in caps)
```

- [ ] **Step 2: Run to verify they fail** → FAIL, path still `compound_loop.backend`.

- [ ] **Step 3: Implement** — repoint `config_path`, and update the existing `test_capabilities.py:390,398,401` assertions that pin the old path.

- [ ] **Step 4: Run to verify they pass** → PASS

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/plugins/builtins.py tests/plugins/test_capabilities.py
git commit -m "fix: point the LLM capability at the live role table"
```

---

### Task 9: `lh doctor` validates the whole role table

**Files:**
- Modify: `src/lazy_harness/cli/doctor_cmd.py:180-210`
- Test: `tests/unit/cli/test_doctor_cmd.py`

**Interfaces:**
- Consumes: `resolve_role`, `LLMConfig`

- [ ] **Step 1: Write the failing tests**

```python
def test_doctor_reports_every_role() -> None:
    out = _doctor(_cfg_with_roles({"classify": "local", "distill": "haiku"}))
    assert "classify" in out and "distill" in out


def test_doctor_flags_a_role_naming_an_undefined_backend() -> None:
    out, ok = _doctor_result(_cfg_with_roles({"classify": "ghost"}))
    assert ok is False
    assert "ghost" in out


def test_doctor_names_the_key_variable_never_its_value(monkeypatch) -> None:
    monkeypatch.setenv("SOME_VAR", "sk-secret")
    out = _doctor(_cfg_with_key_env("SOME_VAR"))
    assert "SOME_VAR" in out
    assert "sk-secret" not in out
```

- [ ] **Step 2: Run to verify they fail** → FAIL.

- [ ] **Step 3: Implement** — iterate the roles, reuse the existing reachability probe per distinct backend, resolve `api_key_env` by name only.

- [ ] **Step 4: Run to verify they pass** → PASS

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/cli/doctor_cmd.py tests/unit/cli/test_doctor_cmd.py
git commit -m "feat: validate the whole role table in lh doctor"
```

---

### Task 10: User-facing documentation

**Files:**
- Modify: `docs/reference/config.md:397-421`, `docs/reference/cli.md`

- [ ] **Step 1: Rewrite the `[compound_loop]` backend rows** to point at `[llm]`, marking `backend`/`backend_options` deprecated with the replacement named.
- [ ] **Step 2: Add a `[llm]` section** documenting `default_role`, `[llm.backends.<name>]` (`type`, `model`, `base_url`, `api_key_env`) and `[llm.roles]`, with the worked Ollama example.
- [ ] **Step 3: Document `lh exec --role`** in the CLI reference: the flag table, the five kinds with their exit codes, the `mode` field, and the `--dry-run` shape.
- [ ] **Step 4: Grep every identifier the new prose names** — env var, field, path, flag — and confirm each exists in the implementation. Anything appearing only in the docs was invented.
- [ ] **Step 5: Run** `uv run --group docs mkdocs build --strict` → clean.
- [ ] **Step 6: Commit**

```bash
git add docs/
git commit -m "docs: document the [llm] role table and lh exec --role"
```

---

### Task 11: Full-gate verification and PR

- [ ] **Step 1:** `uv run pytest` → all green
- [ ] **Step 2:** `uv run ruff check src tests` → clean
- [ ] **Step 3:** `uv run --group docs mkdocs build --strict` → clean
- [ ] **Step 4:** Manual end-to-end against the live Ollama: `printf 'clasifica esto' | lh exec --role classify --dry-run`, then without `--dry-run`. The second is the acceptance test the suite cannot provide.
- [ ] **Step 5:** Open the PR against `main`.

---

## Downstream and release (outside the plan's TDD loop)

- **`lazy-ai-tools`** — `lazy_shared_llm.run()` gains a `role` parameter; `lazy-vault/commands/helpers.py:10` is the only importer. Dispatch a subagent in that repo once `lh` ships the flag, not before: the contract is stable but the binary is not.
- **Release** — merge to `main`, let release-please cut the version, then `uv tool install --reinstall` and **grep site-packages to confirm the code shipped** before touching any `config.toml`. Repository state and deployed state diverge the moment a release is cut.
