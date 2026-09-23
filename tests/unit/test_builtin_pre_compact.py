"""Tests for built-in pre-compact hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from lazy_harness.agents.base import HookEvent
from lazy_harness.hooks.engine import CLI_BOOTSTRAP

# Captured at collection time, before any per-test fixture can patch HOME, so
# it reflects the real machine home regardless of what a test later pins.
_REAL_HOME = Path(os.environ.get("HOME") or Path.home())


def _event(cwd: Path, *, transcript: Path | None = None, profile: str = "") -> HookEvent:
    return HookEvent(
        event="pre_compact",
        profile=profile,
        session_id="s1",
        cwd=cwd,
        transcript_path=transcript,
    )


def _run_through_lh(
    cwd: Path, payload: str, *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Invoke the deployed command, which is how a migrated builtin is reached.

    `python <path>` stops working once `main()` takes a `HookEvent`: the module
    imports, defines `main`, and exits 0 without running anything — the same
    exit code a working hook returns, so a test spawning the bare script could
    no longer tell the two apart. `lh hook` is what `settings.json` carries.

    `env=None` means "inherit", which one test below depends on: it reproduces
    the call shape that leaked into the developer's real home.
    """
    return subprocess.run(
        [sys.executable, "-c", CLI_BOOTSTRAP, "hook", "pre-compact"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=30,
        env=env if env is not None else os.environ.copy(),
        check=False,
    )


def _encoded_cwd(cwd: Path) -> str:
    return "-" + str(cwd).replace("/", "-").lstrip("-")


def test_pre_compact_returns_zero(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps(
            {"role": "user", "content": "hello world from user", "timestamp": "2026-04-12T10:00:00"}
        )
        + "\n"
        + json.dumps({"role": "assistant", "content": "hi", "timestamp": "2026-04-12T10:00:01"})
        + "\n"
    )

    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "CLAUDE_CONFIG_DIR": str(tmp_path / ".claude"),
    }
    (tmp_path / ".claude").mkdir()

    result = _run_through_lh(
        tmp_path,
        json.dumps({"hook_event_name": "PreCompact", "transcript_path": str(transcript)}),
        env=env,
    )
    assert result.returncode == 0, result.stderr


def test_pre_compact_emits_plain_text_carrying_decisions_and_failures_tails(
    tmp_path: Path, monkeypatch
) -> None:
    """The channel, asserted on the decision rather than on a process's stdout.

    Claude Code 2.1.234's `hookSpecificOutput` union has no PreCompact variant,
    so JSON here fails schema validation and the hook is marked failed — its
    output dropped. The executor collects each *successful* hook's raw stdout
    into `newCustomInstructions` instead, which is why `format_hook_output`
    special-cases `pre_compact` and writes `additional_context` as raw text.
    The bytes that reach the summariser are frozen in
    `tests/goldens/hooks/pre-compact/`; this asserts the hook put them on the
    channel the adapter reads.
    """
    from lazy_harness.hooks.builtins.pre_compact import SUMMARY_PREAMBLE, main

    claude_dir = tmp_path / ".claude"
    work = (tmp_path / "work").resolve()
    work.mkdir()
    memory_dir = claude_dir / "projects" / _encoded_cwd(work) / "memory"
    memory_dir.mkdir(parents=True)

    (memory_dir / "decisions.jsonl").write_text(
        json.dumps({"ts": "2026-05-01", "summary": "use uv for packaging"})
        + "\n"
        + json.dumps({"ts": "2026-05-10", "summary": "engram for episodic memory"})
        + "\n"
        + json.dumps({"ts": "2026-05-15", "summary": "pyright-lsp in both profiles"})
        + "\n"
    )
    (memory_dir / "failures.jsonl").write_text(
        json.dumps({"ts": "2026-05-02", "summary": "chezmoi TTY error on apply"})
        + "\n"
        + json.dumps({"ts": "2026-05-12", "summary": "worktree.bgIsolation misread as opt-in"})
        + "\n"
    )

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))

    decision = main(_event(work))

    ctx = decision.additional_context
    assert ctx.startswith(SUMMARY_PREAMBLE)
    assert decision.system_message == ""
    assert decision.verdict is None

    assert "Recent decisions" in ctx
    assert "pyright-lsp in both profiles" in ctx
    assert "engram for episodic memory" in ctx
    assert "Recent failures" in ctx
    assert "worktree.bgIsolation misread as opt-in" in ctx


def test_pre_compact_empty_input(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    work = (tmp_path / "work").resolve()
    work.mkdir()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "CLAUDE_CONFIG_DIR": str(claude_dir),
    }

    result = _run_through_lh(
        work, json.dumps({"hook_event_name": "PreCompact", "cwd": str(work)}), env=env
    )
    assert result.returncode == 0, result.stderr

    # Effect, not just exit code: the hook always creates the memory dir
    # (even with no transcript), so its presence at the pinned location is
    # proof the run stayed inside the sandbox instead of the real machine.
    memory_dir = claude_dir / "projects" / _encoded_cwd(work) / "memory"
    assert memory_dir.is_dir()


def test_pre_compact_subprocess_cannot_leak_into_real_machine_home(tmp_path: Path) -> None:
    """Regression test for the leak this hook's tests caused on the real machine.

    `test_pre_compact_empty_input` used to spawn this hook via `subprocess.run`
    without setting `HOME`/`CLAUDE_CONFIG_DIR` in the child's env. The child
    inherited the *developer's real* environment, so `paths._home()` resolved
    to the real machine home and the hook created a project dir under the real
    `~/.claude-lazy` on every run - 170 stray directories accumulated this way.

    This test reproduces that exact call shape (no `env=` kwarg) and asserts
    the hook never touches the real machine home. Before the `_isolate_home_dir`
    guard in conftest.py existed, this failed - the directory below was really
    created on disk.

    Routed through `lh hook` rather than `python pre_compact.py`: a migrated
    module run as a script exits 0 having done nothing, so the bare-script
    shape would assert the absence of a write no hook was ever going to make.
    The memory-dir assertion is what proves the run actually happened.
    """
    work = (tmp_path / "work").resolve()
    work.mkdir()
    encoded = _encoded_cwd(work)
    real_leak_target = _REAL_HOME / ".claude" / "projects" / encoded

    result = _run_through_lh(work, json.dumps({"hook_event_name": "PreCompact", "cwd": str(work)}))

    assert result.returncode == 0, result.stderr
    assert not real_leak_target.exists(), (
        f"hook subprocess leaked into the real machine home at {real_leak_target}"
    )
    # The run reached the hook: without this the assertion above would pass
    # against a command that never resolved a memory dir at all.
    leaked = sorted(_REAL_HOME.glob(f".claude*/projects/{encoded}"))
    assert leaked == [], leaked


def test_pre_compact_routes_paths_through_agent_adapter(tmp_path, monkeypatch) -> None:
    """ADR-032 L3/L4: memory/backup dirs must come from the configured agent
    adapter. With agent.type = "null" the summary must land under ~/.null even
    when CLAUDE_CONFIG_DIR points elsewhere."""
    import json as _json

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "decoy-claude"))

    cwd = (tmp_path / "proj").resolve()
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")

    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        _json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "please refactor the auth module"},
            }
        )
        + "\n"
    )

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[harness]\nversion = "1"\n\n[agent]\ntype = "null"\n')
    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import pre_compact as hook_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)
    monkeypatch.chdir(cwd)
    hook_mod.main(_event(cwd, transcript=transcript))

    summary_file = home / ".null" / "projects" / encoded / "memory" / "pre-compact-summary.md"
    assert summary_file.is_file()
    assert "please refactor the auth module" in summary_file.read_text()
