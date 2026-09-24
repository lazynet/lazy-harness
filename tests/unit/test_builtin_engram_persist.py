"""Directory routing for the engram-persist builtin, asserted on `main(event)`.

The end-to-end half of what this file used to cover now lives in
`tests/unit/hooks/builtins/test_engram_persist_goldens.py`, which runs the hook
through `lh hook engram-persist` the way a deployed `settings.json` does. What
stays here is the routing claim ADR-032 L3/L4 makes, which is about the
*adapter* rather than about the wire: whatever `CLAUDE_CONFIG_DIR` says, a
profile running `agent.type = "null"` writes under that agent's directories.

`test_wrapper_reads_stdin_and_invokes_engram` was retired rather than ported.
Its value was a pair — the save reached `engram`, and nothing landed in the
`~/.claude` fallback — and both halves are asserted together in
`test_the_run_lands_in_the_invoked_profile_and_not_in_the_global_dir`, against
a profile rather than against an environment variable. Splitting the pair is
what would have lost it.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from lazy_harness.agents.base import HookDecision, HookEvent


def _stop_event(cwd: Path, *, profile: str = "") -> HookEvent:
    """A Stop event built by the adapter, not by hand.

    Hand-constructing the dataclass would let this file disagree with what
    `parse_hook_input` actually produces — which is where trap 1 lives: a
    payload naming no `cwd` yields `Path("")`, and `Path("")` is `Path(".")`.
    """
    from lazy_harness.agents.registry import get_agent

    return get_agent("claude-code").parse_hook_input(
        "session_stop", {"cwd": str(cwd)}, profile=profile
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


def test_hook_routes_paths_through_agent_adapter(
    tmp_path: Path, monkeypatch, declared_null_sessions: None
) -> None:
    """ADR-032 L3/L4: memory/logs dirs must come from the configured agent
    adapter. With agent.type = "null" they must land under ~/.null even when
    CLAUDE_CONFIG_DIR points elsewhere."""
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
        def __init__(
            self,
            *,
            memory_dir: Path,
            logs_dir: Path,
            project_key: str,
            engram_bin: str | None = None,
            cursor_dir: Path | None = None,
            adopt_cursor_dirs: tuple[Path, ...] = (),
        ) -> None:
            captured["memory_dir"] = memory_dir
            captured["logs_dir"] = logs_dir

        def persist_new_entries(self) -> None:
            pass

    monkeypatch.setattr("lazy_harness.knowledge.engram_persist.EngramPersister", FakePersister)

    assert hook_mod.main(_stop_event(cwd)) == HookDecision()

    assert captured["memory_dir"] == home / ".null" / "projects" / encoded / "memory"
    assert captured["logs_dir"] == home / ".null" / "logs"


def test_hook_passes_configured_engram_binary(tmp_path: Path, monkeypatch) -> None:
    """Hook subprocesses inherit a PATH that may lack the binary; config must win."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    cwd = tmp_path / "proj"
    cwd.mkdir()

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[harness]
version = "1"

[memory.engram]
enabled = true
binary = "/opt/homebrew/bin/engram"
"""
    )
    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import engram_persist as hook_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)

    captured: dict[str, object] = {}

    class FakePersister:
        def __init__(
            self,
            *,
            memory_dir: Path,
            logs_dir: Path,
            project_key: str,
            engram_bin: str | None = None,
            cursor_dir: Path | None = None,
            adopt_cursor_dirs: tuple[Path, ...] = (),
        ) -> None:
            captured["engram_bin"] = engram_bin

        def persist_new_entries(self) -> None:
            pass

    monkeypatch.setattr("lazy_harness.knowledge.engram_persist.EngramPersister", FakePersister)

    assert hook_mod.main(_stop_event(cwd)) == HookDecision()

    assert captured["engram_bin"] == "/opt/homebrew/bin/engram"


def test_hook_abstains_when_engram_save_fails(tmp_path: Path, monkeypatch) -> None:
    """A failing `engram save` is a logged no-op, never a decision."""
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

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))
    monkeypatch.setenv("PATH", str(shim_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr(
        "lazy_harness.core.paths.config_file", lambda: tmp_path / "absent-config.toml"
    )

    from lazy_harness.hooks.builtins import engram_persist as hook_mod

    assert hook_mod.main(_stop_event(cwd)) == HookDecision()

    log = (claude_dir / "logs" / "engram_persist.log").read_text()
    assert "engram save returned 1" in log


def test_the_module_no_longer_carries_a_script_entry_point(tmp_path: Path) -> None:
    """The bare-script path is gone, and importing the module still exits 0.

    `main` takes a `HookEvent` now, so a leftover `if __name__ == "__main__":
    main()` would raise `TypeError: main() missing 1 required positional
    argument` and exit 1. No golden covers this: the goldens run `lh hook`, the
    only command anything deploys. What is left is an import with no side
    effects, which is what this asserts.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "lazy_harness.hooks.builtins.engram_persist"],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
