"""Subprocess-level tests for the engram-persist builtin wrapper."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

HOOK_PATH = (
    Path(__file__).parent.parent.parent
    / "src"
    / "lazy_harness"
    / "hooks"
    / "builtins"
    / "engram_persist.py"
)


def _make_engram_shim(shim_dir: Path, exit_code: int = 0) -> Path:
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "engram"
    log = shim_dir / "engram_invocations.log"
    shim.write_text(
        f"#!/usr/bin/env python3\n"
        f"import sys\n"
        f"with open({str(log)!r}, 'a') as f:\n"
        f"    f.write(' '.join(sys.argv) + '\\n')\n"
        f"# A 'version' subcommand is needed by the metrics path:\n"
        f"if len(sys.argv) > 1 and sys.argv[1] == 'version':\n"
        f"    print('engram v0.0.0-shim')\n"
        f"    sys.exit(0)\n"
        f"sys.exit({exit_code})\n"
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim


def test_wrapper_reads_stdin_and_invokes_engram(tmp_path: Path) -> None:
    claude_dir = tmp_path / "claude"
    cwd = tmp_path / "lazy-harness"
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"
    memory_dir.mkdir(parents=True)

    entry = {"ts": "T1", "type": "decision", "summary": "hello"}
    (memory_dir / "decisions.jsonl").write_text(json.dumps(entry) + "\n")

    shim_dir = tmp_path / "shimbin"
    _make_engram_shim(shim_dir, exit_code=0)

    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(claude_dir)
    env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")

    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
    )

    assert result.returncode == 0, result.stderr
    log = (shim_dir / "engram_invocations.log").read_text()
    assert " save hello " in log


def test_wrapper_routes_paths_through_agent_adapter(tmp_path: Path, monkeypatch) -> None:
    """ADR-032 L3/L4: memory/logs dirs must come from the configured agent
    adapter. With agent.type = "null" they must land under ~/.null even when
    CLAUDE_CONFIG_DIR points elsewhere."""
    import io
    import sys as _sys

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "decoy-claude"))

    cwd = tmp_path / "proj"
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[harness]
version = "1"

[agent]
type = "null"
"""
    )
    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import engram_persist as hook_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)

    captured: dict[str, Path] = {}

    class FakePersister:
        def __init__(self, *, memory_dir: Path, logs_dir: Path, project_key: str) -> None:
            captured["memory_dir"] = memory_dir
            captured["logs_dir"] = logs_dir

        def persist_new_entries(self) -> None:
            pass

    monkeypatch.setattr("lazy_harness.knowledge.engram_persist.EngramPersister", FakePersister)
    monkeypatch.setattr(_sys, "stdin", io.StringIO(json.dumps({"cwd": str(cwd)})))
    hook_mod.main()

    assert captured["memory_dir"] == home / ".null" / "projects" / encoded / "memory"
    assert captured["logs_dir"] == home / ".null" / "logs"


def test_wrapper_exits_zero_when_engram_save_fails(tmp_path: Path) -> None:
    claude_dir = tmp_path / "claude"
    cwd = tmp_path / "lazy-harness"
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"
    memory_dir.mkdir(parents=True)

    entry = {"ts": "T1", "type": "decision", "summary": "doomed"}
    (memory_dir / "decisions.jsonl").write_text(json.dumps(entry) + "\n")

    shim_dir = tmp_path / "shimbin"
    _make_engram_shim(shim_dir, exit_code=1)

    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(claude_dir)
    env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")

    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
    )

    assert result.returncode == 0, result.stderr
