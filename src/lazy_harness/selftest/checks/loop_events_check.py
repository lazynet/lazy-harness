"""Post-release check: drive the loop-event hooks and read back what they wrote.

Unit tests import the hooks and call their functions. The agent instead runs
them as scripts, in a different interpreter, against a real repository — and
two attribution bugs reached a release through exactly that gap. This check
closes it: it builds a throwaway git repo, runs the hook files the installed
package actually ships, and asserts on the rows in the resulting store.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from lazy_harness.selftest.result import CheckResult, CheckStatus

GROUP = "loop-events"
_PROMPT = "implementá el hook y agregá el test"
_PROFILE = "selftest"


def _builtin_hooks_dir() -> Path:
    """Directory of the hook scripts in the package that is running."""
    from lazy_harness.hooks import builtins

    return Path(builtins.__file__).parent


def _fail(name: str, message: str) -> CheckResult:
    return CheckResult(group=GROUP, name=name, status=CheckStatus.FAILED, message=message)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "user.email=selftest@local", "-c", "user.name=selftest", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _build_repo(root: Path) -> tuple[Path, Path, Path]:
    """Repo with an artifact subdirectory and a linked worktree."""
    repo = root / "repo"
    repo.mkdir()
    _git(["init", "-q"], repo)
    _git(["commit", "-q", "--allow-empty", "-m", "init"], repo)
    subdir = repo / "artifacts-out"
    subdir.mkdir()
    worktree = repo / ".worktrees" / "probe"
    _git(["worktree", "add", "-q", str(worktree), "-b", "probe"], repo)
    return repo, subdir, worktree


def _write_config(root: Path, db_path: Path, profile_dir: Path) -> None:
    (root / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        f'[monitoring]\nenabled = true\ndb = "{db_path}"\n\n'
        f'[profiles]\ndefault = "{_PROFILE}"\n\n'
        f'[profiles.{_PROFILE}]\nconfig_dir = "{profile_dir}"\nroots = ["~"]\n'
    )


def _run_hook(hook: Path, payload: dict[str, str], env: dict[str, str]) -> str:
    """Run a hook script the way the agent does. Returns '' on success."""
    if not hook.is_file():
        return f"{hook.name} not found in {hook.parent}"
    proc = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        return f"{hook.name} exited {proc.returncode}: {proc.stderr.strip()[:200]}"
    return ""


def _rows(db_path: Path, kind: str) -> list[tuple[str, str]]:
    if not db_path.is_file():
        return []
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT project, profile FROM loop_events WHERE kind = ? ORDER BY ts", (kind,)
        ).fetchall()


def check_loop_events(*, hooks_dir: Path | None = None) -> list[CheckResult]:
    """Verify loop-event attribution end to end against the running package."""
    hooks = hooks_dir if hooks_dir is not None else _builtin_hooks_dir()

    try:
        with tempfile.TemporaryDirectory(prefix="lh-loop-events-") as tmp:
            return _probe(Path(tmp), hooks)
    except FileNotFoundError:
        return [
            CheckResult(
                group=GROUP,
                name="git",
                status=CheckStatus.WARNING,
                message="git not on PATH; loop-event attribution not verified",
            )
        ]
    except subprocess.CalledProcessError as e:
        return [_fail("repo", f"could not build the probe repo: {e.stderr or e}".strip())]
    except Exception as e:  # never take down `lh selftest`
        return [_fail("probe", f"{type(e).__name__}: {e}")]


def _probe(root: Path, hooks: Path) -> list[CheckResult]:
    repo, subdir, worktree = _build_repo(root)
    db_path = root / "metrics.db"
    profile_dir = root / "agent-config"
    profile_dir.mkdir()
    _write_config(root, db_path, profile_dir)

    env = os.environ.copy()
    env["LH_CONFIG_DIR"] = str(root)
    env["CLAUDE_CONFIG_DIR"] = str(profile_dir)

    results: list[CheckResult] = []
    prompt_hook = hooks / "user_prompt_goal.py"
    end_hook = hooks / "session_end.py"

    for hook, payload in (
        (prompt_hook, {"session_id": "s1", "prompt": _PROMPT, "cwd": str(subdir)}),
        (prompt_hook, {"session_id": "s2", "prompt": _PROMPT, "cwd": str(worktree)}),
        (end_hook, {"session_id": "s3", "cwd": str(subdir)}),
    ):
        error = _run_hook(hook, payload, env)
        if error:
            results.append(_fail("hook-run", error))

    prompts = _rows(db_path, "nontrivial_prompt")
    closed = _rows(db_path, "session_closed")
    expected = str(repo.resolve())

    results.append(
        _expect(
            "project-from-subdirectory",
            actual=prompts[0][0] if len(prompts) > 0 else None,
            expected=expected,
            hint="a hook launched from an artifact subdirectory must record the repo",
        )
    )
    results.append(
        _expect(
            "project-from-worktree",
            actual=prompts[1][0] if len(prompts) > 1 else None,
            expected=expected,
            hint="a hook launched from a worktree must record the main checkout",
        )
    )
    results.append(
        _expect(
            "session-closed-project",
            actual=closed[0][0] if closed else None,
            expected=expected,
            hint="session_closed must carry a project so it can be grouped",
        )
    )
    results.append(
        _expect(
            "profile-recorded",
            actual=prompts[0][1] if prompts else None,
            expected=_PROFILE,
            hint="rows from different profiles share one store and must be labelled",
        )
    )
    return results


def _expect(name: str, *, actual: str | None, expected: str, hint: str) -> CheckResult:
    if actual is None:
        return _fail(name, f"no row recorded — {hint}")
    if actual != expected:
        return _fail(name, f"recorded {actual!r}, expected {expected!r} — {hint}")
    return CheckResult(group=GROUP, name=name, status=CheckStatus.PASSED)
