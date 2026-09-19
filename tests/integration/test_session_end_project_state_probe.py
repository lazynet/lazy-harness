"""ADR-062 installed-agent probes: SessionEnd queues the task, the vault waits.

The hook is invoked through the real CLI entry point under a claude-code
profile and a codex profile. What it must prove is narrow: a compound-loop
task naming this session lands in *that* profile's queue, the worker spawn is
requested, and the project readme the worker will later edit is byte-identical
when the hook returns. Persistence itself is exercised in the worker process
(`tests/unit/test_compound_loop.py`), never here and never against a real
vault: `lazymind_dir` points at a throwaway tree under `tmp_path`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.knowledge.project_state import SECTION_HEADER

_CONFIG = """\
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "cc"

[profiles.cc]
config_dir = "{cc}"
roots = []

[profiles.cx]
config_dir = "{cx}"
roots = []
agent = "codex"

[compound_loop]
enabled = true
lazymind_dir = "{vault}"
"""

_SESSION_ID = "probe-session-0001"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    prj_dir = tmp_path / "vault" / "1-Projects" / "PRJ-Probe"
    prj_dir.mkdir(parents=True)
    (prj_dir / "PRJ-Probe.md").write_text(
        f"---\ntype: project\nupdated: 2026-09-14\n---\n# PRJ-Probe\n\n"
        f"{SECTION_HEADER}\n\nold snapshot\n\n## Backlog\n\n### Pendiente — Alta prioridad\n\n",
        encoding="utf-8",
    )
    return tmp_path / "vault"


@pytest.fixture
def profiles(
    tmp_path: Path, home_dir: Path, vault: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Path]:
    lh_config = tmp_path / "lhconfig"
    lh_config.mkdir()
    dirs = {"cc": tmp_path / "cc-home", "cx": tmp_path / "cx-home"}
    (lh_config / "config.toml").write_text(
        _CONFIG.format(cc=dirs["cc"], cx=dirs["cx"], vault=vault), encoding="utf-8"
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "lhdata"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return dirs


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record the worker spawn instead of running it: the probe ends at the queue."""
    from lazy_harness.hooks.builtins import session_end as hook_mod

    calls: list[list[str]] = []
    monkeypatch.setattr(hook_mod.subprocess, "Popen", lambda argv, **kw: calls.append(list(argv)))
    return calls


def _transcript(tmp_path: Path, cwd: Path) -> Path:
    transcript = tmp_path / "transcripts" / f"{_SESSION_ID}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"type": "permission-mode"},
        {"type": "system", "cwd": str(cwd)},
        {"type": "user", "message": {"content": "a" * 250}},
        {"type": "assistant", "message": {"content": "ok"}},
    ]
    transcript.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return transcript


def _vault_bytes(vault: Path) -> dict[Path, bytes]:
    return {p.relative_to(vault): p.read_bytes() for p in vault.rglob("*") if p.is_file()}


@pytest.mark.parametrize("profile", ["cc", "cx"], ids=["claude-code", "codex"])
def test_session_end_queues_the_task_and_leaves_the_vault_untouched(
    profile: str,
    profiles: dict[str, Path],
    vault: Path,
    spawned: list[list[str]],
    tmp_path: Path,
) -> None:
    from lazy_harness.core.config import load_config
    from lazy_harness.core.paths import config_file
    from lazy_harness.hooks.builtins._shared import agent_dir_for

    _, runtime_dir = agent_dir_for(load_config(config_file()), profile)
    assert runtime_dir == profiles[profile]
    cwd = tmp_path / "probe"
    cwd.mkdir()
    transcript = _transcript(tmp_path, cwd)
    vault_before = _vault_bytes(vault)

    result = CliRunner().invoke(
        cli,
        ["hook", "session-end", "--profile", profile],
        input=json.dumps(
            {
                "hook_event_name": "SessionEnd",
                "session_id": _SESSION_ID,
                "cwd": str(cwd),
                "transcript_path": str(transcript),
            }
        ),
    )

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    tasks = list((profiles[profile] / "queue").glob("*.task"))
    assert len(tasks) == 1, (profiles[profile] / "logs" / "hooks.log").read_text()
    task = tasks[0].read_text(encoding="utf-8")
    assert f"session_id={_SESSION_ID}" in task
    assert f"cwd={cwd}" in task
    assert f"session_jsonl={transcript}" in task
    assert spawned and "lazy_harness.knowledge.compound_loop_worker" in spawned[0]
    assert _vault_bytes(vault) == vault_before


def test_session_end_queues_nowhere_but_the_invoked_profile(
    profiles: dict[str, Path], vault: Path, spawned: list[list[str]], tmp_path: Path
) -> None:
    cwd = tmp_path / "probe"
    cwd.mkdir()
    transcript = _transcript(tmp_path, cwd)

    result = CliRunner().invoke(
        cli,
        ["hook", "session-end", "--profile", "cx"],
        input=json.dumps(
            {"session_id": _SESSION_ID, "cwd": str(cwd), "transcript_path": str(transcript)}
        ),
    )

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert len(list((profiles["cx"] / "queue").glob("*.task"))) == 1
    assert not (profiles["cc"] / "queue").exists()
