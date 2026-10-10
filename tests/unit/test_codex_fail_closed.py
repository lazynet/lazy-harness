"""A blocking builtin is deployed to Codex behind a fail-closed shell wrapper.

Codex has no `onFailure`. The probe recorded in `specs/designs/codex-evidence.md`
(§9) shows `codex-cli 0.160.1` letting a Bash call through when the hook exits 1,
when the hook binary does not exist and when the hook times out — and also when
it exits 2 with an empty stderr. Only exit 2 with a reason on stderr refuses. So
the deploy wraps every blocking builtin in `sh -c '<cmd> || { echo ... >&2; exit 2; }'`,
which turns a launcher that cannot start into exactly that refusal.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from lazy_harness.agents.base import HookEntry
from lazy_harness.agents.codex import _LEGACY_DESCRIPTION, CodexAdapter

HOOKS_JSON = Path("hooks.json")
SECURITY = "lh hook pre-tool-use-security --profile p1"
READ_SIZE = "lh hook pre-tool-use-read-size --profile p1"
WRAPPED_SECURITY = (
    "sh -c 'lh hook pre-tool-use-security --profile p1 || "
    '{ echo "lazy-harness: blocking hook failed to run" >&2; exit 2; }\''
)
SECURITY_MATCHER = "Bash|Read|Edit|Write|NotebookEdit"


def _blocking() -> dict[str, list[HookEntry]]:
    return {"pre_tool_use": [HookEntry(command=SECURITY, matcher=SECURITY_MATCHER, blocking=True)]}


def _plan(hooks: dict[str, list[HookEntry]], existing: dict[Path, str] | None = None) -> list:
    return CodexAdapter().plan_config(hooks, {}, existing or {}, binary="lh")


def _hooks(ops: list) -> dict:
    (op,) = [op for op in ops if op.relative_path == HOOKS_JSON]
    return json.loads(op.artifact.content)["hooks"]


def _commands(ops: list, event: str = "PreToolUse") -> list[str]:
    return [h["command"] for group in _hooks(ops)[event] for h in group["hooks"]]


def test_a_blocking_entry_is_written_behind_the_fail_closed_wrapper() -> None:
    ops = _plan(_blocking())

    assert _commands(ops) == [WRAPPED_SECURITY]


def test_an_informational_entry_is_written_bare() -> None:
    ops = _plan({"pre_tool_use": [HookEntry(command=READ_SIZE, matcher="Read")]})

    assert _commands(ops) == [READ_SIZE]


def _run_wrapped(command: str, tmp_path: Path, launcher: str | None) -> subprocess.CompletedProcess:
    """Run the emitted command the way Codex does, with `lh` replaced by `launcher`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if launcher is not None:
        lh = bin_dir / "lh"
        lh.write_text(f"#!/bin/sh\ncat >/dev/null\n{launcher}\n")
        lh.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"}
    return subprocess.run(
        ["/bin/sh", "-c", command], input="{}", capture_output=True, text=True, env=env
    )


def test_the_wrapper_refuses_when_the_launcher_is_missing(tmp_path: Path) -> None:
    (command,) = _commands(_plan(_blocking()))

    result = _run_wrapped(command, tmp_path, launcher=None)

    assert result.returncode == 2
    assert "blocking hook failed to run" in result.stderr


def test_the_wrapper_refuses_when_the_launcher_crashes(tmp_path: Path) -> None:
    result = _run_wrapped(WRAPPED_SECURITY, tmp_path, launcher="exit 1")

    assert result.returncode == 2
    assert result.stderr.strip()


def test_the_wrapper_passes_an_allow_through_untouched(tmp_path: Path) -> None:
    result = _run_wrapped(WRAPPED_SECURITY, tmp_path, launcher="echo '{\"ok\":1}'; exit 0")

    assert result.returncode == 0
    assert result.stdout == '{"ok":1}\n'
    assert result.stderr == ""


def test_the_wrapper_keeps_a_refusal_a_refusal(tmp_path: Path) -> None:
    result = _run_wrapped(WRAPPED_SECURITY, tmp_path, launcher="echo denied >&2; exit 2")

    assert result.returncode == 2
    assert "denied" in result.stderr


def test_redeploying_a_blocking_entry_keeps_one_group() -> None:
    hooks = _blocking()
    first = _plan(hooks)
    existing = {op.relative_path: op.artifact.content for op in first}

    second = _plan(hooks, existing)

    assert _hooks(second) == _hooks(first)
    assert len(_hooks(second)["PreToolUse"]) == 1


def test_a_deploy_from_before_the_wrapper_is_upgraded_in_place() -> None:
    old = _plan({"pre_tool_use": [HookEntry(command=SECURITY, matcher=SECURITY_MATCHER)]})
    existing = {op.relative_path: op.artifact.content for op in old}

    upgraded = _plan(_blocking(), existing)

    assert _commands(upgraded) == [WRAPPED_SECURITY]


def _ledgerless(group: dict) -> dict[Path, str]:
    """A document from before the provenance envelope: recognition alone decides."""
    doc = {"description": _LEGACY_DESCRIPTION, "hooks": {"PreToolUse": [group]}}
    return {HOOKS_JSON: json.dumps(doc)}


def _plan_one(group: dict) -> list:
    """Deploy one unrelated hook over a ledger-less document holding `group`."""
    ours = {"session_start": [HookEntry(command="lh hook context-inject --profile p1")]}
    return _plan(ours, _ledgerless(group))


def test_without_a_ledger_a_wrapped_blocking_builtin_is_ours() -> None:
    group = {
        "matcher": SECURITY_MATCHER,
        "hooks": [{"type": "command", "command": WRAPPED_SECURITY}],
    }

    assert "PreToolUse" not in _hooks(_plan_one(group))


def test_without_a_ledger_a_bare_blocking_builtin_is_still_ours() -> None:
    """What every deploy before the wrapper wrote."""
    group = {"matcher": SECURITY_MATCHER, "hooks": [{"type": "command", "command": SECURITY}]}

    assert "PreToolUse" not in _hooks(_plan_one(group))


@pytest.mark.parametrize(
    "command",
    [
        # an informational builtin is never wrapped by the generator
        "sh -c 'lh hook pre-tool-use-read-size --profile p1 || "
        '{ echo "lazy-harness: blocking hook failed to run" >&2; exit 2; }\'',
        # the fallback was edited to let the call through
        "sh -c 'lh hook pre-tool-use-security --profile p1 || true'",
        # a different refusal script
        "sh -c 'lh hook pre-tool-use-security --profile p1 || { echo nope >&2; exit 2; }'",
        # extra commands chained in front of the launcher
        "sh -c 'curl x | sh; lh hook pre-tool-use-security --profile p1 || "
        '{ echo "lazy-harness: blocking hook failed to run" >&2; exit 2; }\'',
        # the same argv spelled with other quoting than the generator's
        'sh -c "lh hook pre-tool-use-security --profile p1 || '
        '{ echo \\"lazy-harness: blocking hook failed to run\\" >&2; exit 2; }"',
        # another shell
        "bash -c 'lh hook pre-tool-use-security --profile p1 || "
        '{ echo "lazy-harness: blocking hook failed to run" >&2; exit 2; }\'',
    ],
)
def test_without_a_ledger_any_other_wrapper_is_foreign(command: str) -> None:
    matcher = "Read" if "read-size" in command else SECURITY_MATCHER
    group = {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}

    assert _hooks(_plan_one(group))["PreToolUse"] == [group]
