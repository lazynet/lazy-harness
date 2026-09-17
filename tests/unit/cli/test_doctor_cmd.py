"""Unit tests for lh doctor."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.agents.base import HookSupport
from lazy_harness.agents.registry import NullAdapter

_BASE_TOML = (
    '[harness]\nversion = "1"\n'
    '[agent]\ntype = "claude-code"\n'
    '[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "~/.claude-p1"\n'
    '[knowledge]\nroot = ""\n'
)


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(_BASE_TOML)
    return cfg


def test_doctor_warns_when_ruff_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _write_config(tmp_path)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.shutil.which", lambda _name: None)
    runner = CliRunner()
    result = runner.invoke(doctor, [])
    assert "ruff not found" in result.output.lower()


def test_doctor_does_not_warn_when_ruff_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _write_config(tmp_path)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setattr(
        "lazy_harness.cli.doctor_cmd.shutil.which",
        lambda name: "/opt/bin/ruff" if name == "ruff" else None,
    )
    runner = CliRunner()
    result = runner.invoke(doctor, [])
    assert "ruff not found" not in result.output.lower()


def test_doctor_renders_features_section(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from lazy_harness.cli.doctor_cmd import doctor
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    cfg = _write_config(tmp_path)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.shutil.which", lambda _name: None)
    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: False)

    runner = CliRunner()
    result = runner.invoke(doctor, [])

    assert "Features" in result.output
    assert "qmd" in result.output
    assert "engram" in result.output
    assert "graphify" in result.output


def test_engram_persist_metrics_path_routes_through_agent_adapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ADR-032 L3: the metrics path must come from the agent adapter, not a
    hardcoded ~/.claude fallback.

    Exercised on the no-profile branch, which is the one this claim is about:
    with a profile the answer comes from its `config_dir` instead, and
    `test_doctor_reads_the_engram_metrics_the_hook_writes` covers that half.
    """
    from lazy_harness.agents.registry import NullAdapter
    from lazy_harness.cli.doctor_cmd import _engram_persist_metrics_path

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "decoy-claude"))

    result = _engram_persist_metrics_path(NullAdapter(), None, "")

    assert result == home / ".null" / "logs" / "engram_persist_metrics.jsonl"


# --- LLM backend section (ADR-033) ---


def _recording_console():
    import io

    from rich.console import Console

    buf = io.StringIO()
    return Console(file=buf, force_terminal=False), buf


def test_render_llm_backend_claude_ok_when_binary_on_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.cli.doctor_cmd import _render_llm_backend
    from lazy_harness.core.config import Config

    monkeypatch.setattr(
        "lazy_harness.cli.doctor_cmd.shutil.which",
        lambda name: "/opt/bin/claude" if name == "claude" else None,
    )
    console, buf = _recording_console()
    assert _render_llm_backend(console, Config()) is True
    assert "claude" in buf.getvalue()


def test_render_llm_backend_claude_missing_binary_is_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.cli.doctor_cmd import _render_llm_backend
    from lazy_harness.core.config import Config

    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.shutil.which", lambda _name: None)
    console, buf = _recording_console()
    assert _render_llm_backend(console, Config()) is True
    assert "not found" in buf.getvalue()


def test_render_llm_backend_ollama_reachable(
    monkeypatch: pytest.MonkeyPatch, expects_deprecated_compound_loop: None
) -> None:
    from lazy_harness.cli.doctor_cmd import _render_llm_backend
    from lazy_harness.core.config import Config

    captured: dict = {}

    def fake_get(url, **kwargs):  # noqa: ANN001, ANN003
        captured["url"] = url
        captured["timeout"] = kwargs.get("timeout")
        return object()

    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.httpx.get", fake_get)
    console, buf = _recording_console()
    cfg = Config()
    cfg.compound_loop.backend = "ollama"
    assert _render_llm_backend(console, cfg) is True
    assert captured["url"] == "http://localhost:11434"
    assert captured["timeout"] == 2
    assert "reachable" in buf.getvalue()


def test_render_llm_backend_unreachable_is_warning_not_failure(
    monkeypatch: pytest.MonkeyPatch, expects_deprecated_compound_loop: None
) -> None:
    import httpx

    from lazy_harness.cli.doctor_cmd import _render_llm_backend
    from lazy_harness.core.config import Config

    def fake_get(url, **kwargs):  # noqa: ANN001, ANN003
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.httpx.get", fake_get)
    console, buf = _recording_console()
    cfg = Config()
    cfg.compound_loop.backend = "mlx"
    assert _render_llm_backend(console, cfg) is True
    assert "not reachable" in buf.getvalue()


def test_render_llm_backend_unknown_backend_fails(
    monkeypatch: pytest.MonkeyPatch, expects_deprecated_compound_loop: None
) -> None:
    from lazy_harness.cli.doctor_cmd import _render_llm_backend
    from lazy_harness.core.config import Config

    console, buf = _recording_console()
    cfg = Config()
    cfg.compound_loop.backend = "no-such-backend"
    assert _render_llm_backend(console, cfg) is False
    out = buf.getvalue()
    assert "no-such-backend" in out
    assert "ollama" in out


def test_doctor_output_includes_llm_backend_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _write_config(tmp_path)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.shutil.which", lambda _name: None)
    runner = CliRunner()
    result = runner.invoke(doctor, [])
    assert "LLM roles" in result.output


# --- Artifact versions section (decision 9) ---


def test_render_artifact_versions_silent_when_nothing_newer() -> None:
    """No section printed when every artifact matches the running binary —
    same rule as `_render_sink_freshness`: an absent problem is silent."""
    from lazy_harness.cli.doctor_cmd import _render_artifact_versions
    from lazy_harness.core.artifact_version import ArtifactVersionReport

    console, buf = _recording_console()
    reports = [
        ArtifactVersionReport("p1", "settings.json", Path("/x/settings.json"), "0.1.0"),
    ]
    _render_artifact_versions(console, reports, installed_version="99.0.0")
    assert buf.getvalue() == ""


def test_render_artifact_versions_reports_a_newer_artifact() -> None:
    from lazy_harness.cli.doctor_cmd import _render_artifact_versions
    from lazy_harness.core.artifact_version import ArtifactVersionReport

    console, buf = _recording_console()
    reports = [
        ArtifactVersionReport("p1", "settings.json", Path("/x/settings.json"), "99.0.0"),
    ]
    _render_artifact_versions(console, reports, installed_version="0.1.0")
    out = buf.getvalue()
    assert "p1" in out
    assert "settings.json" in out
    assert "99.0.0" in out
    assert "0.1.0" in out


def test_doctor_reports_a_settings_json_newer_than_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End-to-end: `lh doctor` surfaces a settings.json written by a newer
    lazy-harness than the one currently running. Reporting, not refusing —
    the command still exits 0."""
    from lazy_harness.cli.doctor_cmd import doctor

    agent_cfg_dir = tmp_path / "agentcfg"
    agent_cfg_dir.mkdir()
    (agent_cfg_dir / "settings.json").write_text('{"lh_version": "9999.0.0", "hooks": {}}')

    toml = (
        '[harness]\nversion = "1"\n'
        '[agent]\ntype = "claude-code"\n'
        f'[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "{agent_cfg_dir}"\n'
        '[knowledge]\nroot = ""\n'
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(toml)

    profiles_dir = tmp_path / "harness-config" / "profiles"
    profiles_dir.mkdir(parents=True)

    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setattr(
        "lazy_harness.cli.doctor_cmd.config_dir", lambda: tmp_path / "harness-config"
    )
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.shutil.which", lambda _name: None)

    runner = CliRunner()
    result = runner.invoke(doctor, [])

    assert "Artifact versions" in result.output
    assert "9999.0.0" in result.output
    assert result.exit_code == 0


def _linked_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Build a main checkout plus a linked worktree; return (repo_root, worktree)."""
    repo = tmp_path / "repo"
    (repo / ".git" / "worktrees" / "wt").mkdir(parents=True)
    worktree = repo / ".worktrees" / "wt"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {repo / '.git' / 'worktrees' / 'wt'}\n")
    return repo, worktree


def test_project_memory_dir_resolves_worktree_to_main_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Memory lives under the main checkout's key, not the worktree's."""
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.cli.doctor_cmd import _project_memory_dir

    runtime = tmp_path / "runtime"
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.agent_runtime_dir", lambda _agent: runtime)
    repo, worktree = _linked_worktree(tmp_path)
    monkeypatch.chdir(worktree)

    encoded = "-" + str(repo).replace("/", "-").lstrip("-")
    assert (
        _project_memory_dir(get_agent("claude-code"), None, "")
        == runtime / "projects" / encoded / "memory"
    )


def test_project_memory_dir_uses_cwd_outside_a_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.cli.doctor_cmd import _project_memory_dir

    runtime = tmp_path / "runtime"
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.agent_runtime_dir", lambda _agent: runtime)
    repo = tmp_path / "plain"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(repo)

    encoded = "-" + str(repo).replace("/", "-").lstrip("-")
    assert (
        _project_memory_dir(get_agent("claude-code"), None, "")
        == runtime / "projects" / encoded / "memory"
    )


def test_render_memory_hygiene_skips_when_no_memory_dir(tmp_path: Path) -> None:
    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene

    console, buf = _recording_console()
    assert _render_memory_hygiene(console, tmp_path / "missing") is True
    assert "Memory hygiene" not in buf.getvalue()


def test_render_memory_hygiene_reports_healthy_state(tmp_path: Path) -> None:
    from datetime import datetime

    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene

    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("\n".join(f"- line {i}" for i in range(10)) + "\n")
    (memory / "claude-md.proposal.md").write_text(
        "## 2026-06-10T09:00:00-03:00\n\n- **Rule:** keep it simple\n  - **Rationale:** because\n"
    )
    (memory / "claude-md.accepted.md").write_text("- **Rule:** old accepted rule\n")
    (memory / "claude-md.rejected.md").write_text("- **Rule:** old rejected rule\n")

    console, buf = _recording_console()
    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assert _render_memory_hygiene(console, memory, now=now) is True
    out = buf.getvalue()
    assert "Memory hygiene" in out
    assert "10/200" in out
    assert "/12KB" in out
    assert "1 pending" in out
    assert "1 accepted" in out
    assert "1 rejected" in out


def test_render_memory_hygiene_warns_near_memory_cap(tmp_path: Path) -> None:
    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene

    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("\n".join(f"- line {i}" for i in range(185)) + "\n")

    console, buf = _recording_console()
    assert _render_memory_hygiene(console, memory) is True
    assert "185/200" in buf.getvalue()
    assert "!" in buf.getvalue()


def test_render_memory_hygiene_fails_over_memory_cap(tmp_path: Path) -> None:
    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene

    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("\n".join(f"- line {i}" for i in range(205)) + "\n")

    console, buf = _recording_console()
    assert _render_memory_hygiene(console, memory) is False
    assert "205/200" in buf.getvalue()


def test_render_memory_hygiene_warns_near_byte_cap(tmp_path: Path) -> None:
    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene
    from lazy_harness.hooks.builtins.pre_tool_use_memory_size import MAX_BYTES

    memory = tmp_path / "memory"
    memory.mkdir()
    dense = "\n".join("- " + "x" * 368 for _ in range(30)) + "\n"
    assert MAX_BYTES * 0.9 <= len(dense.encode("utf-8")) <= MAX_BYTES
    (memory / "MEMORY.md").write_text(dense)

    console, buf = _recording_console()
    assert _render_memory_hygiene(console, memory) is True
    assert "!" in buf.getvalue()
    assert "11.1/12KB" in buf.getvalue()


def test_render_memory_hygiene_fails_over_byte_cap(tmp_path: Path) -> None:
    """A dense index breaches the byte ceiling long before the line ceiling."""
    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene
    from lazy_harness.hooks.builtins.pre_tool_use_memory_size import MAX_BYTES

    memory = tmp_path / "memory"
    memory.mkdir()
    dense = "\n".join("- " + "x" * 400 for _ in range(60)) + "\n"
    assert len(dense.encode("utf-8")) > MAX_BYTES
    assert len(dense.splitlines()) < 200
    (memory / "MEMORY.md").write_text(dense)

    console, buf = _recording_console()
    assert _render_memory_hygiene(console, memory) is False
    assert "24.2/12KB" in buf.getvalue()


def test_render_memory_hygiene_warns_on_stale_pending_proposals(tmp_path: Path) -> None:
    from datetime import datetime

    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene

    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "claude-md.proposal.md").write_text(
        "## 2026-05-01T10:00:00-03:00\n\n- **Rule:** stale rule\n  - **Rationale:** old\n"
    )

    console, buf = _recording_console()
    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assert _render_memory_hygiene(console, memory, now=now) is True
    out = buf.getvalue()
    assert "1 pending" in out
    assert "41d" in out
    assert "lh memory proposals" in out


# --- codex hook trust footer (lane B3, deploy-retrust) ----------------------


def test_render_codex_trust_prints_the_retrust_instruction_footer() -> None:
    """Pinned byte-for-byte before the instruction text moves to codex_trust.py."""
    import io

    from rich.console import Console

    from lazy_harness.agents.codex_trust import CodexHookTrust
    from lazy_harness.cli.doctor_cmd import _render_codex_trust

    report = CodexHookTrust(
        profile="probe",
        hooks_file=Path("/tmp/probe/hooks.json"),
        config_file=Path("/tmp/probe/config.toml"),
        untrusted=("pre_tool_use[0]",),
    )
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=200)
    _render_codex_trust(console, [report])
    # Whitespace-normalised: rich wraps at the console width regardless of how
    # wide we make it, so the pin asserts on the words, not the line breaks.
    out = " ".join(buf.getvalue().split())
    assert (
        "Codex will not run a hook it has not approved, and says nothing when it "
        "skips one. Approve them in Codex's own review screen — `lh deploy` cannot: "
        "the User config layer it writes to is never Managed."
    ) in out


# --- role table validation (ADR-039) -----------------------------------------


def _cfg_with_roles(roles: dict[str, str], backends: dict | None = None):
    from lazy_harness.core.config import Config, LLMBackendConfig, LLMConfig

    cfg = Config()
    cfg.llm = LLMConfig(
        backends=backends
        if backends is not None
        else {"local": LLMBackendConfig(type="ollama", model="qwen2.5-coder:7b")},
        roles=roles,
    )
    return cfg


def _render(cfg, monkeypatch: pytest.MonkeyPatch) -> tuple[str, bool]:
    import io

    from rich.console import Console

    from lazy_harness.cli import doctor_cmd as mod

    monkeypatch.setattr(mod.httpx, "get", lambda *a, **kw: None)
    buf = io.StringIO()
    ok = mod._render_llm_backend(Console(file=buf, width=200), cfg)
    return buf.getvalue(), ok


def test_doctor_reports_every_role(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.core.config import LLMBackendConfig

    cfg = _cfg_with_roles(
        {"classify": "local", "distill": "haiku"},
        {
            "local": LLMBackendConfig(type="ollama"),
            "haiku": LLMBackendConfig(type="claude"),
        },
    )
    out, ok = _render(cfg, monkeypatch)
    assert "classify" in out
    assert "distill" in out
    assert ok is True


def test_doctor_flags_a_role_naming_an_undefined_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, ok = _render(_cfg_with_roles({"classify": "ghost"}, {}), monkeypatch)
    assert ok is False
    assert "ghost" in out


def test_doctor_names_the_key_variable_never_its_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import LLMBackendConfig

    monkeypatch.setenv("SOME_LLM_KEY", "sk-secret")
    cfg = _cfg_with_roles(
        {"classify": "remote"},
        {
            "remote": LLMBackendConfig(
                type="openai-compatible",
                base_url="http://x/v1",
                api_key_env="SOME_LLM_KEY",
            )
        },
    )
    out, _ = _render(cfg, monkeypatch)
    assert "SOME_LLM_KEY" in out
    assert "sk-secret" not in out


def test_doctor_still_reports_the_deprecated_single_backend_form(
    monkeypatch: pytest.MonkeyPatch, expects_deprecated_compound_loop: None
) -> None:
    """A config with no [llm] table must not silently report nothing."""
    from lazy_harness.core.config import Config

    cfg = Config()
    cfg.compound_loop.backend = "ollama"
    out, ok = _render(cfg, monkeypatch)
    assert ok is True
    assert "ollama" in out


_SIGNAL_GAP_TOML = (
    '[harness]\nversion = "1"\n'
    '[agent]\ntype = "claude-code"\n'
    '[profiles]\ndefault = "p1"\n\n'
    '[profiles.p1]\nconfig_dir = "~/.claude-p1"\nagent = "no-reader"\n'
    '[hooks.session_stop]\nscripts = ["stop-verify-guard"]\n'
    '[knowledge]\nroot = ""\n'
)


def _unwrapped(output: str) -> str:
    """Rich hard-wraps at the console width; assertions are about words."""
    return " ".join(output.split())


class _NoReaderAdapter(NullAdapter):
    """Delivers Stop, implements no `TranscriptReader`."""

    @property
    def name(self) -> str:
        return "no-reader"

    def hook_events(self) -> dict[str, HookSupport]:
        return {"session_stop": HookSupport(native_name="Stop")}


def test_doctor_names_the_missing_signal_of_a_deployed_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.agents import registry
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = tmp_path / "config.toml"
    cfg.write_text(_SIGNAL_GAP_TOML)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setitem(registry._AGENTS, "no-reader", _NoReaderAdapter)

    output = _unwrapped(CliRunner().invoke(doctor, []).output)

    assert "Hook signals" in output
    assert "p1/stop-verify-guard" in output
    assert "the hook needs signal goal_status" in output


def test_doctor_hook_signal_line_names_the_signal_state_not_the_event_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The design keeps "event absent" and "signal absent" apart.

    Their resolutions differ — an event vocabulary versus a `TranscriptReader`
    — so the line has to say which one it is instead of "unavailable".
    """
    from lazy_harness.agents import registry
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = tmp_path / "config.toml"
    cfg.write_text(_SIGNAL_GAP_TOML)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setitem(registry._AGENTS, "no-reader", _NoReaderAdapter)

    output = _unwrapped(CliRunner().invoke(doctor, []).output)

    assert "session_stop is delivered, but the hook needs signal" in output
    assert "no-reader has no TranscriptReader" in output
    assert "Missing signal, not a missing event" in output


def test_doctor_hook_signal_hint_says_the_hook_is_left_out_of_the_deploy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The hint describes what deploy now does, not what it used to do.

    It read "the hook installs, runs, finds nothing and passes" while nothing
    stopped that from happening. `_hook_entries_for` now skips the hook, so the
    old sentence describes a behaviour the code no longer has — a diagnostic
    that outlived the defect it reported.
    """
    from lazy_harness.agents import registry
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = tmp_path / "config.toml"
    cfg.write_text(_SIGNAL_GAP_TOML)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setitem(registry._AGENTS, "no-reader", _NoReaderAdapter)

    output = _unwrapped(CliRunner().invoke(doctor, []).output)

    assert "deploy leaves the hook out" in output
    assert "installs, runs, finds nothing and passes" not in output


def test_doctor_omits_hook_signals_when_the_agent_delivers_everything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = tmp_path / "config.toml"
    cfg.write_text(_SIGNAL_GAP_TOML.replace('agent = "no-reader"\n', ""))
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)

    assert "Hook signals" not in _unwrapped(CliRunner().invoke(doctor, []).output)


# --- hook_events() surface: operations and event vocabulary (step 10) ------


def test_render_hook_operations_silent_when_nothing_inert() -> None:
    from lazy_harness.cli.doctor_cmd import _render_hook_operations

    console, buf = _recording_console()
    _render_hook_operations(console, [])
    assert buf.getvalue() == ""


def test_render_hook_operations_names_a_partially_inert_hook() -> None:
    from lazy_harness.agents.base import Operation
    from lazy_harness.cli.doctor_cmd import _render_hook_operations
    from lazy_harness.hooks.event_surface import HookOperationGap

    console, buf = _recording_console()
    gap = HookOperationGap(
        profile="cx",
        agent="codex",
        event="pre_tool_use",
        hook="pre-tool-use-security",
        inert=(Operation.READ_FILE,),
        fully_inert=False,
    )
    _render_hook_operations(console, [gap])
    out = _unwrapped(buf.getvalue())

    assert "Hook operations" in out
    assert "cx/pre-tool-use-security" in out
    assert "pre_tool_use is delivered" in out
    assert "read_file" in out
    assert "can't see those calls" in out


def test_render_hook_operations_names_a_fully_inert_hook() -> None:
    from lazy_harness.agents.base import Operation
    from lazy_harness.cli.doctor_cmd import _render_hook_operations
    from lazy_harness.hooks.event_surface import HookOperationGap

    console, buf = _recording_console()
    gap = HookOperationGap(
        profile="cx",
        agent="codex",
        event="pre_tool_use",
        hook="pre-tool-use-read-size",
        inert=(Operation.READ_FILE,),
        fully_inert=True,
    )
    _render_hook_operations(console, [gap])
    out = _unwrapped(buf.getvalue())

    assert "the hook is inert on this profile" in out
    assert "can't see those calls" not in out


def test_render_uncarried_events_silent_when_nothing_uncarried() -> None:
    from lazy_harness.cli.doctor_cmd import _render_uncarried_events

    console, buf = _recording_console()
    _render_uncarried_events(console, [])
    assert buf.getvalue() == ""


def test_render_uncarried_events_names_the_hook_and_event() -> None:
    from lazy_harness.cli.doctor_cmd import _render_uncarried_events
    from lazy_harness.hooks.event_surface import UncarriedEventHook

    console, buf = _recording_console()
    gap = UncarriedEventHook(
        profile="p1", agent="session-only", event="session_stop", hook="stop-verify-guard"
    )
    _render_uncarried_events(console, [gap])
    out = _unwrapped(buf.getvalue())

    assert "Hook events" in out
    assert "p1/stop-verify-guard" in out
    assert "wired to session_stop" in out
    assert "session-only does not deliver at all" in out
    assert "nothing installs and nothing runs" in out


class _SessionOnlyAdapter(NullAdapter):
    """Delivers `session_start` only — every other deployed hook is uncarried."""

    @property
    def name(self) -> str:
        return "session-only"

    def hook_events(self) -> dict[str, HookSupport]:
        return {"session_start": HookSupport(native_name="SessionStart")}


_UNCARRIED_EVENT_TOML = (
    '[harness]\nversion = "1"\n'
    '[agent]\ntype = "claude-code"\n'
    '[profiles]\ndefault = "p1"\n\n'
    '[profiles.p1]\nconfig_dir = "~/.claude-p1"\nagent = "session-only"\n'
    '[hooks.session_stop]\nscripts = ["stop-verify-guard"]\n'
    '[knowledge]\nroot = ""\n'
)


def test_doctor_reports_an_uncarried_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from lazy_harness.agents import registry
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = tmp_path / "config.toml"
    cfg.write_text(_UNCARRIED_EVENT_TOML)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setitem(registry._AGENTS, "session-only", _SessionOnlyAdapter)

    output = _unwrapped(CliRunner().invoke(doctor, []).output)

    assert "Hook events" in output
    assert "p1/stop-verify-guard" in output
    assert "wired to session_stop" in output


def _codex_default_hooks_config(tmp_path: Path) -> Path:
    """A Codex profile with no hooks.json — cfg.hooks is empty, so the full
    default hook set is what gets checked for operation coverage."""
    profile_dir = tmp_path / "codex-home"
    profile_dir.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n'
        '[agent]\ntype = "claude-code"\n'
        '[profiles]\ndefault = "cx"\n\n'
        f'[profiles.cx]\nconfig_dir = "{profile_dir}"\nagent = "codex"\n'
        '[knowledge]\nroot = ""\n'
    )
    return cfg


def test_doctor_reports_codexs_read_file_operation_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _codex_default_hooks_config(tmp_path)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)

    output = _unwrapped(CliRunner().invoke(doctor, []).output)

    assert "Hook operations" in output
    assert "cx/pre-tool-use-security" in output
    assert "cx/pre-tool-use-read-size" in output
    assert "the hook is inert on this profile" in output


def test_doctor_omits_the_new_hook_event_surface_sections_for_claude_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: _write_config(tmp_path))
    from lazy_harness.cli.doctor_cmd import doctor

    output = _unwrapped(CliRunner().invoke(doctor, []).output)

    assert "Hook operations" not in output
    assert "Hook events" not in output


def test_doctor_reads_the_engram_metrics_the_hook_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second pair of paths that answer one question, asserted to agree.

    `engram-persist` names its metrics file with `agent_dir_for(cfg,
    event.profile)`. `doctor` named the file it reads globally, and nothing
    compared them — so the hook recorded every run under the profile while
    `doctor` reported "No runs yet (Stop hook not triggered)" from the global
    directory, which is the health state a hook that never fires produces.
    A diagnostic that cannot distinguish "working" from "never ran" is worse
    than none.

    `CLAUDE_CONFIG_DIR` is cleared: it outranks the profile's `config_dir`, so
    pinning it would make both sides agree for the wrong reason.
    """
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.cli.doctor_cmd import _engram_persist_metrics_path
    from lazy_harness.core.config import load_config
    from lazy_harness.hooks.builtins._shared import agent_dir_for

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f"""
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "alpha"

[profiles.alpha]
config_dir = "{tmp_path / "alpha-home"}"
"""
    )
    cfg = load_config(cfg_file)

    agent, writer_dir = agent_dir_for(cfg, "alpha")
    logs = agent.session_dirs().get("logs") or "logs"
    written = writer_dir / logs / "engram_persist_metrics.jsonl"

    assert _engram_persist_metrics_path(get_agent("claude-code"), cfg, "alpha") == written


def test_doctor_reads_the_memory_dir_the_hook_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third pair of paths that answer one question, asserted to agree.

    `session-end` names the memory dir with `agent_dir_for(cfg, event.profile)`
    — the profile's agent, the profile's directory, that agent's `sessions`
    subdirectory. `doctor` named it from `[agent].type` and had no way to be
    told which profile it was diagnosing, so under a profile running a second
    agent its memory-hygiene section reported on a directory nothing writes to.

    `CLAUDE_CONFIG_DIR` is cleared: it outranks the profile's `config_dir`, so
    pinning it would make both sides agree for the wrong reason.
    """
    from lazy_harness.agents import registry
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.cli.doctor_cmd import _project_memory_dir
    from lazy_harness.core.config import load_config
    from lazy_harness.hooks.builtins._shared import agent_dir_for, knowledge_root_for
    from lazy_harness.hooks.builtins._shared import memory_dir as shared_memory_dir

    class _OtherAdapter(registry.NullAdapter):
        @property
        def name(self) -> str:
            return "other"

        def env_var(self) -> str:
            return "OTHER_CONFIG_DIR"

        def session_dirs(self) -> dict[str, str]:
            return {"sessions": "threads", "logs": "journal", "queue": "outbox"}

    monkeypatch.setitem(registry._AGENTS, "other", _OtherAdapter)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("OTHER_CONFIG_DIR", raising=False)

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "alpha"\n\n'
        f'[profiles.alpha]\nconfig_dir = "{tmp_path / "alpha-home"}"\nagent = "other"\n'
    )
    cfg = load_config(cfg_file)

    writer_agent, writer_dir = agent_dir_for(cfg, "alpha")
    written = shared_memory_dir(
        None,
        agent_dir=writer_dir,
        sessions_subdir=writer_agent.session_dirs().get("sessions") or "projects",
        cwd=Path.cwd(),
        knowledge_root=knowledge_root_for(cfg),
    )

    assert _project_memory_dir(get_agent("claude-code"), cfg, "alpha") == written


# --- Codex hook trust -----------------------------------------------------


def _codex_profile(tmp_path: Path, *, hooks: bool = True) -> Path:
    """A Codex profile with a deployed `hooks.json`, and the config naming it."""
    from lazy_harness.agents.base import HookEntry
    from lazy_harness.agents.codex import CodexAdapter

    profile_dir = tmp_path / "codex-home"
    profile_dir.mkdir()
    if hooks:
        ops = CodexAdapter().plan_config(
            {"pre_tool_use": [HookEntry(command="lh hook pre-tool-use-security --profile cx")]},
            {},
            {},
        )
        assert ops[0].artifact is not None
        (profile_dir / "hooks.json").write_text(ops[0].artifact.content)

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n'
        '[agent]\ntype = "claude-code"\n'
        '[profiles]\ndefault = "cx"\n\n'
        f'[profiles.cx]\nconfig_dir = "{profile_dir}"\nagent = "codex"\n'
        '[knowledge]\nroot = ""\n'
    )
    return cfg


def test_doctor_reports_an_untrusted_codex_hook_and_never_calls_one_trusted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The state right after `lh deploy`, and the one Codex expresses as silence.

    `trusted` is absent from the vocabulary on purpose: establishing it needs
    the hash Codex recomputes, which the harness declines to reimplement.
    """
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _codex_profile(tmp_path)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)

    output = _unwrapped(CliRunner().invoke(doctor, []).output)

    assert "Codex hook trust" in output
    assert "cx — 1 of 1 deployed hook untrusted" in output
    assert "trusted hook" not in output


def test_doctor_calls_a_stored_hash_unknown_rather_than_trusted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.agents.codex import trust_keys
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _codex_profile(tmp_path)
    hooks_file = tmp_path / "codex-home" / "hooks.json"
    declared, _ = trust_keys(hooks_file, hooks_file.read_text())
    (tmp_path / "codex-home" / "config.toml").write_text(
        f'[hooks.state."{declared[0][0]}"]\ntrusted_hash = "sha256:abc"\n'
    )
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)

    output = _unwrapped(CliRunner().invoke(doctor, []).output)

    assert "1 hook carries a stored hash" in output
    assert "whether it still matches is not determinable" in output
    assert "untrusted" not in output


def test_doctor_names_an_orphaned_trust_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The one state the harness establishes alone: the key is position-scoped,
    so a redeploy that drops a group strands its approval."""
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _codex_profile(tmp_path)
    hooks_file = tmp_path / "codex-home" / "hooks.json"
    (tmp_path / "codex-home" / "config.toml").write_text(
        f'[hooks.state."{hooks_file}:session_start:4:0"]\ntrusted_hash = "sha256:abc"\n'
    )
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)

    output = _unwrapped(CliRunner().invoke(doctor, []).output)

    assert "1 orphaned trust entry" in output


def test_doctor_says_so_when_the_trust_state_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reporting "0 untrusted" over an unreadable file looks like the good
    outcome, which makes it the worst of the three."""
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _codex_profile(tmp_path)
    (tmp_path / "codex-home" / "config.toml").write_text("[hooks.state\nbroken")
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)

    output = _unwrapped(CliRunner().invoke(doctor, []).output)

    assert "trust state not readable" in output
    assert "untrusted" not in output


def test_doctor_trust_reports_without_failing_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Untrusted is the *expected* state right after a deploy, so failing on it
    would make the documented happy path red. Same rule as `Hook signals`."""
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _codex_profile(tmp_path)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)

    result = CliRunner().invoke(doctor, [])

    assert "Codex hook trust" in _unwrapped(result.output)
    assert result.exit_code == 0


def test_doctor_omits_the_section_for_a_profile_with_no_deployed_hooks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _codex_profile(tmp_path, hooks=False)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)

    assert "Codex hook trust" not in _unwrapped(CliRunner().invoke(doctor, []).output)


def test_doctor_omits_the_section_entirely_without_a_codex_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: _write_config(tmp_path))
    from lazy_harness.cli.doctor_cmd import doctor

    assert "Codex hook trust" not in _unwrapped(CliRunner().invoke(doctor, []).output)


# --- profile credentials (ADR-045 D3) --------------------------------------


def _secrets_config(secrets_dir: Path, *, profiles: tuple[str, ...], default: str):
    from lazy_harness.core.config import Config, ProfileEntry

    cfg = Config()
    cfg.secrets.dir = str(secrets_dir)
    cfg.profiles.default = default
    cfg.profiles.items = {n: ProfileEntry(config_dir=f"~/.claude-{n}") for n in profiles}
    return cfg


def test_render_profile_secrets_is_silent_when_only_the_default_exists(tmp_path: Path) -> None:
    """One profile takes its credentials from the environment by definition.

    The section exists to catch a *second* account quietly wearing the first
    one's credential; with one profile there is no second account to confuse it
    with, and a line saying so every run is how a section stops being read.
    """
    from lazy_harness.cli.doctor_cmd import _render_profile_secrets

    console, buf = _recording_console()
    _render_profile_secrets(console, _secrets_config(tmp_path, profiles=("p1",), default="p1"))

    assert buf.getvalue() == ""


def test_render_profile_secrets_names_a_profile_with_no_file_of_its_own(tmp_path: Path) -> None:
    """The visible half of the F2 fix: the launch refuses an unreadable file,
    and this reports the case the launch cannot refuse — no file at all, which
    is legitimate for exactly one profile and silent inheritance for the rest."""
    from lazy_harness.cli.doctor_cmd import _render_profile_secrets

    cfg = _secrets_config(tmp_path, profiles=("p1", "flex"), default="p1")

    console, buf = _recording_console()
    _render_profile_secrets(console, cfg)
    out = buf.getvalue()

    assert "flex.env" in out
    assert "inherits" in out


def test_render_profile_secrets_leaves_the_default_profile_alone(tmp_path: Path) -> None:
    """The default profile having no file is the documented normal case, not a
    finding — `core/secrets.py` says so and the overlay's fail-open path is
    built around it."""
    from lazy_harness.cli.doctor_cmd import _render_profile_secrets

    cfg = _secrets_config(tmp_path, profiles=("p1", "flex"), default="p1")
    (tmp_path / "flex.env").write_text("TOKEN=placeholder-not-a-real-value\n")

    console, buf = _recording_console()
    _render_profile_secrets(console, cfg)

    assert buf.getvalue() == ""


def test_render_profile_secrets_never_prints_what_is_in_the_file(tmp_path: Path) -> None:
    """`lh doctor` output is pasted into issues and scrollback."""
    from lazy_harness.cli.doctor_cmd import _render_profile_secrets

    cfg = _secrets_config(tmp_path, profiles=("p1", "flex", "other"), default="p1")
    (tmp_path / "flex.env").write_text("TOKEN=PLACEHOLDER-SENTINEL-VALUE\n")

    console, buf = _recording_console()
    _render_profile_secrets(console, cfg)
    out = buf.getvalue()

    assert "PLACEHOLDER-SENTINEL-VALUE" not in out
    assert "other.env" in out


def test_render_profile_secrets_stays_quiet_when_the_directory_cannot_be_read(
    tmp_path: Path,
) -> None:
    """A directory this cannot traverse is not a profile inheriting silently.

    `resolve_launch` refuses that profile outright, which is a far louder signal
    than a doctor line; reporting it here as "inherits the environment" would be
    a guess, and the wrong one.
    """
    from lazy_harness.cli.doctor_cmd import _render_profile_secrets

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "flex.env").write_text("TOKEN=placeholder-not-a-real-value\n")
    secrets_dir.chmod(0o000)
    cfg = _secrets_config(secrets_dir, profiles=("p1", "flex"), default="p1")

    try:
        console, buf = _recording_console()
        _render_profile_secrets(console, cfg)
    finally:
        secrets_dir.chmod(0o700)

    assert buf.getvalue() == ""


def test_doctor_reports_a_profile_that_inherits_its_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Wired into the command, not only unit-tested next to it."""
    from lazy_harness.cli.doctor_cmd import doctor

    secrets = tmp_path / "secrets"
    secrets.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n'
        '[agent]\ntype = "claude-code"\n'
        f'[secrets]\ndir = "{secrets}"\n'
        '[profiles]\ndefault = "p1"\n\n'
        '[profiles.p1]\nconfig_dir = "~/.claude-p1"\n\n'
        '[profiles.flex]\nconfig_dir = "~/.claude-flex"\n'
        '[knowledge]\nroot = ""\n'
    )
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)

    result = CliRunner().invoke(doctor, [])

    assert "flex.env" in result.output


# --- Transcripts section ----------------------------------------------------


def _transcript_output(tmp_path: Path, agents: dict[str, str]) -> str:
    """Render the transcripts section for one config with `agents` profiles."""
    import io

    from rich.console import Console

    from lazy_harness.cli.doctor_cmd import _render_transcripts
    from lazy_harness.core.config import Config, HarnessConfig, ProfileEntry

    cfg = Config(harness=HarnessConfig(version="1"))
    cfg.profiles.default = next(iter(agents))
    cfg.profiles.items = {
        name: ProfileEntry(config_dir=str(tmp_path / name), agent=agent)
        for name, agent in agents.items()
    }
    buf = io.StringIO()
    _render_transcripts(Console(file=buf, width=140, force_terminal=False, no_color=True), cfg)
    return buf.getvalue()


def test_doctor_reports_ok_when_a_reader_has_transcripts(tmp_path: Path) -> None:
    d = tmp_path / "lazy" / "projects" / "-repo"
    d.mkdir(parents=True)
    (d / "s.jsonl").write_text("{}\n")

    out = _transcript_output(tmp_path, {"lazy": "claude-code"})
    assert "lazy" in out
    assert "has a reader for" in out
    # Never "reads": a reader existing is not a consumer reading it.
    assert "claude-code reads" not in out


def test_doctor_reports_degraded_when_transcripts_have_no_reader(tmp_path: Path) -> None:
    """Copilot's `session-state/events.jsonl`: present, and nothing opens it."""
    d = tmp_path / "cop" / "session-state" / "abc"
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text("{}\n")

    out = _transcript_output(tmp_path, {"cop": "copilot"})
    assert "unread" in out
    assert "copilot" in out


def test_doctor_reports_no_transcript_as_normal_not_degraded(tmp_path: Path) -> None:
    (tmp_path / "cx" / "sessions").mkdir(parents=True)

    out = _transcript_output(tmp_path, {"cx": "codex"})
    assert "unread" not in out
    assert "no transcripts" in out


def test_doctor_names_an_agent_that_declares_no_sessions_directory(tmp_path: Path) -> None:
    """The `Path(x) / ""` trap, at the site the design wrote the snippet for.

    `settings.json` is the file the rejected one-liner finds when it globs the
    config directory itself, which is what makes `null` read as degraded.
    """
    (tmp_path / "np").mkdir(parents=True)
    (tmp_path / "np" / "settings.json").write_text("{}")

    out = _transcript_output(tmp_path, {"np": "null"})
    assert "declares no sessions directory" in out
    assert "unread" not in out


def test_doctor_reports_one_line_per_profile(tmp_path: Path) -> None:
    """Four profiles, four agents, four verdicts, one run."""
    (tmp_path / "lazy" / "projects" / "-r").mkdir(parents=True)
    (tmp_path / "lazy" / "projects" / "-r" / "s.jsonl").write_text("{}\n")
    (tmp_path / "cop" / "session-state" / "a").mkdir(parents=True)
    (tmp_path / "cop" / "session-state" / "a" / "events.jsonl").write_text("{}\n")
    (tmp_path / "cx" / "sessions").mkdir(parents=True)
    (tmp_path / "np").mkdir(parents=True)

    out = _transcript_output(
        tmp_path,
        {"lazy": "claude-code", "cop": "copilot", "cx": "codex", "np": "null"},
    )
    body = [ln for ln in out.splitlines() if ln.startswith("  ")]
    assert len(body) == 4
    assert [ln.split()[1] for ln in body] == ["lazy", "cop", "cx", "np"]


def test_doctor_transcript_verdict_survives_an_adapter_without_session_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A duck-typed attribute, exercised with the attribute absent."""
    import io

    from rich.console import Console

    from lazy_harness.cli.doctor_cmd import _render_transcripts
    from lazy_harness.core.config import Config, HarnessConfig, ProfileEntry

    class _NoSessionDirs:
        name = "improvised"

    monkeypatch.setattr(
        "lazy_harness.agents.registry.agent_for_profile", lambda _cfg, _name: _NoSessionDirs()
    )
    cfg = Config(harness=HarnessConfig(version="1"))
    cfg.profiles.default = "x"
    cfg.profiles.items = {"x": ProfileEntry(config_dir=str(tmp_path / "x"), agent="claude-code")}
    (tmp_path / "x").mkdir()

    buf = io.StringIO()
    _render_transcripts(Console(file=buf, width=140, force_terminal=False, no_color=True), cfg)
    assert "declares no sessions directory" in buf.getvalue()


def test_doctor_prints_the_transcripts_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The render is wired into `doctor()`, not merely defined.

    A function nothing calls passes every unit test it has.
    """
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _write_config(tmp_path)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    result = CliRunner().invoke(doctor, [])
    assert "Transcripts" in result.output
