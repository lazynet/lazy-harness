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
    hardcoded ~/.claude fallback."""
    from lazy_harness.agents.registry import NullAdapter
    from lazy_harness.cli.doctor_cmd import _engram_persist_metrics_path

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "decoy-claude"))

    result = _engram_persist_metrics_path(NullAdapter())

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
        _project_memory_dir(get_agent("claude-code"), None)
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
        _project_memory_dir(get_agent("claude-code"), None)
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


def _cfg_with_agents(global_agent: str, profile_agents: dict[str, str]):
    from lazy_harness.core.config import (
        AgentConfig,
        Config,
        HarnessConfig,
        ProfileEntry,
        ProfilesConfig,
    )

    return Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type=global_agent),
        profiles=ProfilesConfig(
            default=next(iter(profile_agents)),
            items={
                name: ProfileEntry(config_dir=f"~/.cfg-{name}", agent=agent)
                for name, agent in profile_agents.items()
            },
        ),
    )


def test_doctor_warns_a_profile_agent_the_deploy_path_does_not_honour_yet() -> None:
    """`[profiles.<name>].agent` is honoured by `.envrc` but not by hook or MCP
    config generation, which still resolves the global agent for every profile.

    A profile declaring its own agent therefore receives the global agent's
    settings.json shape, silently. Until the remaining `cfg.agent.type` readers
    move, the gap has to be visible rather than found via a broken profile.
    """
    from rich.console import Console

    from lazy_harness.cli.doctor_cmd import _render_unhonoured_profile_agents

    cfg = _cfg_with_agents("claude-code", {"personal": "", "experiment": "null"})

    console = Console(force_terminal=False, width=200)
    with console.capture() as cap:
        _render_unhonoured_profile_agents(console, cfg)
    out = cap.get()

    assert "experiment" in out, out
    assert "null" in out, out
    assert "personal" not in out, "a profile inheriting the global agent is not a warning"


def test_doctor_is_silent_when_no_profile_declares_a_divergent_agent() -> None:
    from rich.console import Console

    from lazy_harness.cli.doctor_cmd import _render_unhonoured_profile_agents

    # "work" declares an agent, but the same one: nothing diverges.
    cfg = _cfg_with_agents("claude-code", {"personal": "", "work": "claude-code"})

    console = Console(force_terminal=False, width=200)
    with console.capture() as cap:
        _render_unhonoured_profile_agents(console, cfg)

    assert cap.get() == ""


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


def test_doctor_omits_hook_signals_when_the_agent_delivers_everything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = tmp_path / "config.toml"
    cfg.write_text(_SIGNAL_GAP_TOML.replace('agent = "no-reader"\n', ""))
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)

    assert "Hook signals" not in _unwrapped(CliRunner().invoke(doctor, []).output)
