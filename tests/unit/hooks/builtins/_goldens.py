"""Run a builtin the way the agent does, and freeze all three channels.

`specs/designs/2026-09-13-multi-agent-harness-design.md` gates the runner
migration on bytes: for each builtin, stdout, stderr and the exit code are
captured on every branch *before* the migration, and identity is asserted
after. Two of the three hooks refuse through channels a return value would not
show — `pre_tool_use_security` writes stderr and exits 2, `stop_verify_guard`
writes JSON on stdout — so a harness that captured a return value, or stdout
alone, would not cover the refusals at all. Hence a process boundary.

Determinism is bought with a pinned environment rather than with normalisation
wherever it can be: the child gets its own HOME, its own config and data dirs,
a fixed timezone and a PATH that cannot reach an optional binary the developer
happens to have installed. What genuinely cannot be pinned — git's abbreviated
SHA, whose width git chooses from the object count — is normalised by an
explicit rule the calling test names and justifies.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.hooks.engine import CLI_BOOTSTRAP

#: Committed goldens. One directory per hook, one JSON file per branch.
GOLDEN_ROOT = Path(__file__).resolve().parents[4] / "tests" / "goldens" / "hooks"

#: Set to capture or re-capture golden files. Never set during a normal run:
#: a missing golden must fail, because a hook whose golden was never captured
#: was never migrated safely.
CAPTURE_ENV = "LH_CAPTURE_GOLDENS"

#: Ordered (needle, replacement) pairs applied to stdout and stderr alike.
NormalisationRules = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class HookRun:
    """What the agent sees after a hook process exits."""

    stdout: str
    stderr: str
    exit_code: int


def pinned_env(
    *,
    home: Path,
    config_dir: Path,
    data_dir: Path,
    agent_config_dir: Path,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """The child's whole environment — nothing is inherited by accident.

    `LH_CONFIG_DIR` and `LH_DATA_DIR` are what `core.paths` reads first, so the
    hook resolves its config and its metrics store inside the test's tmp tree.
    `CLAUDE_CONFIG_DIR` is the Claude Code adapter's own variable, which decides
    the runtime dir the hooks log and read sessions under.

    `PATH` holds git and nothing else: `context_inject` shells out to git, and
    also to `qmd` when the section is enabled. Inheriting the ambient PATH would
    make the golden depend on whether the machine capturing it had `qmd`.
    """
    git = shutil.which("git")
    if git is None:  # pragma: no cover - git is a hard dependency of the suite
        raise RuntimeError("git is required to capture hook goldens")
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LH_CONFIG_DIR": str(config_dir),
        "LH_DATA_DIR": str(data_dir),
        "CLAUDE_CONFIG_DIR": str(agent_config_dir),
        "PATH": str(Path(git).parent),
        # A hook that renders a date renders it in the local zone.
        "TZ": "UTC",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
    }
    if "PYTHONPATH" in os.environ:
        env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    if extra:
        env.update(extra)
    return env


def run_builtin(module: str, *, stdin_text: str, cwd: Path, env: dict[str, str]) -> HookRun:
    """Execute `python -m <module>` over stdin and capture the three channels.

    `sys.executable` rather than a bare `python`: the pinned PATH has no
    interpreter on it, and a system python without the package installed would
    capture an ImportError as though it were the hook's behaviour.
    """
    proc = subprocess.run(
        [sys.executable, "-m", module],
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(cwd),
        env=env,
        timeout=60,
        check=False,
    )
    return HookRun(stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode)


def run_through_runner(hook: str, *, stdin_text: str, cwd: Path, env: dict[str, str]) -> HookRun:
    """Execute the deployed command — `lh hook <name>` — and capture three channels.

    `python -m <module>` stops reaching a migrated builtin: once `main()` takes
    a `HookEvent` the module's `__main__` block dies on the missing argument.
    The bytes that matter were never the module's anyway — they are the ones
    the command in `settings.json` writes, and that command is this one. It is
    also the only path on which the adapter's `format_hook_output` reaches
    stdout, which is exactly what the identity assertion is about.

    Invoked through `-c` rather than a console script: the pinned PATH has no
    `lh` on it, and `sys.executable` is what guarantees the interpreter that
    has the package installed.
    """
    proc = subprocess.run(
        [sys.executable, "-c", CLI_BOOTSTRAP, "hook", hook],
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(cwd),
        env=env,
        timeout=60,
        check=False,
    )
    return HookRun(stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode)


def normalise_run(run: HookRun, rules: NormalisationRules) -> HookRun:
    """Apply each rule to stdout and stderr, in the order given."""

    def apply(text: str) -> str:
        for needle, replacement in rules:
            text = text.replace(needle, replacement)
        return text

    return HookRun(stdout=apply(run.stdout), stderr=apply(run.stderr), exit_code=run.exit_code)


def golden_path(hook: str, case: str, *, root: Path | None = None) -> Path:
    return (root or GOLDEN_ROOT) / hook / f"{case}.json"


def _serialise(run: HookRun) -> str:
    return (
        json.dumps(
            {"exit_code": run.exit_code, "stderr": run.stderr, "stdout": run.stdout},
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )


def assert_golden(hook: str, case: str, run: HookRun, *, root: Path | None = None) -> None:
    """Compare a run against its committed golden, byte for byte."""
    path = golden_path(hook, case, root=root)
    actual = _serialise(run)
    if os.environ.get(CAPTURE_ENV):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        return
    if not path.is_file():
        raise AssertionError(
            f"golden {hook}/{case} was never captured: {path} does not exist. "
            f"Re-run with {CAPTURE_ENV}=1 to capture it."
        )
    expected = path.read_text(encoding="utf-8")
    if actual != expected:
        raise AssertionError(
            f"golden {hook}/{case} does not match.\n--- expected ---\n{expected}"
            f"--- actual ---\n{actual}"
        )


def short_temp_root() -> Path | None:
    """A temp root short enough that a truncating hook cuts the same way here.

    `pre_tool_use_security` caps its matched text at `MAX_MATCH_LEN`, so a case
    whose payload resolves against the temp directory would have the cut land
    at a different character on a machine whose temp path is longer — the
    golden would encode pytest's path length rather than the hook's behaviour.
    `/tmp` is short and present on both CI platforms; when it is not writable
    there is nothing deterministic to capture, and the caller skips.
    """
    candidate = Path("/tmp")
    if not (os.name == "posix" and os.access(candidate, os.W_OK)):
        return None
    return candidate
