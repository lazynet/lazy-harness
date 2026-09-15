"""Post-release check: drive the loop-event hooks and read back what they wrote.

Unit tests import the hooks and call their functions. The agent instead runs
them in a different interpreter, against a real repository — and two
attribution bugs reached a release through exactly that gap. This check
closes it: it builds a throwaway git repo, drives the hooks the installed
package actually ships, and asserts on the rows in the resulting store.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from lazy_harness.selftest.result import CheckResult, CheckStatus

GROUP = "loop-events"

#: How the check drives one hook: `(name, payload, env)`, returning "" on
#: success and the failure text otherwise. The one seam a test can stand in
#: for now that both hooks here are migrated — see `_run_hook`.
HookInvoker = Callable[[str, dict[str, str], dict[str, str]], str]

_PROMPT = "implementá el hook y agregá el test"
_PROFILE = "selftest"


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


def _run_hook(name: str, payload: dict[str, str], env: dict[str, str]) -> str:
    """Run a hook the way the agent does. Returns '' on success.

    One shape, because every hook this check drives is migrated: a migrated
    builtin is not a script at all. Its `main()` takes a `HookEvent` and the
    module has no `__main__` block, so `python user_prompt_goal.py` reads stdin
    from nobody, calls nothing and exits 0 — the same exit code the working
    hook returns, which is how a check that kept executing files would report a
    green run against hooks it never invoked.

    `--profile` is passed explicitly: it is what the deployed command carries
    and what the `profile-recorded` expectation below is about.
    """
    from lazy_harness.hooks.engine import CLI_BOOTSTRAP

    proc = subprocess.run(
        [sys.executable, "-c", CLI_BOOTSTRAP, "hook", name, "--profile", _PROFILE],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        return f"{name} exited {proc.returncode}: {proc.stderr.strip()[:200]}"
    return ""


def _rows(db_path: Path, kind: str) -> list[tuple[str, str]]:
    if not db_path.is_file():
        return []
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT project, profile FROM loop_events WHERE kind = ? ORDER BY ts", (kind,)
        ).fetchall()


def check_loop_events(*, invoke: HookInvoker | None = None) -> list[CheckResult]:
    """Verify loop-event attribution end to end against the running package.

    `invoke` replaces how each hook is run, and exists so that a test can feed
    this checker a case it must *fail* as well as one it must pass. It replaced
    a `hooks_dir` override that named a directory of hook scripts: once both
    hooks here were migrated nothing read that directory any more, so passing
    it changed nothing and the red test it existed for went green against a
    checker that was working fine.
    """
    run = invoke if invoke is not None else _run_hook

    try:
        with tempfile.TemporaryDirectory(prefix="lh-loop-events-") as tmp:
            return _probe(Path(tmp), run)
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


def _probe(root: Path, run: HookInvoker) -> list[CheckResult]:
    repo, subdir, worktree = _build_repo(root)
    db_path = root / "metrics.db"
    profile_dir = root / "agent-config"
    profile_dir.mkdir()
    _write_config(root, db_path, profile_dir)

    env = os.environ.copy()
    env["LH_CONFIG_DIR"] = str(root)
    env["CLAUDE_CONFIG_DIR"] = str(profile_dir)

    results: list[CheckResult] = []

    for name, payload in (
        ("user-prompt-goal", {"session_id": "s1", "prompt": _PROMPT, "cwd": str(subdir)}),
        ("user-prompt-goal", {"session_id": "s2", "prompt": _PROMPT, "cwd": str(worktree)}),
        ("session-end", {"session_id": "s3", "cwd": str(subdir)}),
    ):
        error = run(name, payload, env)
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
