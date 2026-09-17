"""Tests for the golden-capture harness the three migrated builtins are frozen with.

The harness is what makes `specs/designs/2026-09-13-multi-agent-harness-design.md`'s
"proven by bytes" gate enforceable: it runs a builtin the way the agent does —
as a process, over stdin — and compares all three channels against a committed
file. These tests cover the harness itself, so a golden that silently stops
comparing is a failure here rather than a green run everywhere.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    HookRun,
    assert_golden,
    golden_path,
    normalise_run,
    pinned_env,
    run_builtin,
)

_NOISY_MODULE = """\
import sys
sys.stdout.write("out-bytes\\n")
sys.stderr.write("err-bytes\\n")
sys.exit(2)
"""


@pytest.fixture
def noisy_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A throwaway module that writes to all three channels."""
    pkg = tmp_path / "noisy_hook.py"
    pkg.write_text(_NOISY_MODULE)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    return "noisy_hook"


def test_run_builtin_captures_all_three_channels(noisy_module: str, tmp_path: Path) -> None:
    run = run_builtin(
        noisy_module,
        stdin_text="",
        cwd=tmp_path,
        env={"PYTHONPATH": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )

    assert run.stdout == "out-bytes\n"
    assert run.stderr == "err-bytes\n"
    assert run.exit_code == 2


def test_run_builtin_feeds_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "echo_hook.py").write_text("import sys\nsys.stdout.write(sys.stdin.read())\n")
    run = run_builtin(
        "echo_hook",
        stdin_text='{"a": 1}',
        cwd=tmp_path,
        env={"PYTHONPATH": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )

    assert run.stdout == '{"a": 1}'


def test_run_builtin_runs_in_the_given_cwd(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "cwd_hook.py").write_text("import os, sys\nsys.stdout.write(os.getcwd())\n")
    run = run_builtin(
        "cwd_hook",
        stdin_text="",
        cwd=work,
        env={"PYTHONPATH": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )

    assert Path(run.stdout).resolve() == work.resolve()


def test_pinned_env_fixes_timezone_and_excludes_the_ambient_path(tmp_path: Path) -> None:
    env = pinned_env(
        home=tmp_path / "home",
        config_dir=tmp_path / "cfg",
        data_dir=tmp_path / "data",
        agent_config_dir=tmp_path / "claude",
    )

    # A hook that renders a timestamp renders it in the runner's zone; UTC is
    # the only zone every machine agrees on.
    assert env["TZ"] == "UTC"
    assert env["LH_CONFIG_DIR"] == str(tmp_path / "cfg")
    assert env["LH_DATA_DIR"] == str(tmp_path / "data")
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "claude")
    assert env["HOME"] == str(tmp_path / "home")
    # An inherited PATH lets an optional binary on the developer's machine
    # (qmd, say) change a golden that CI would capture differently.
    assert env["PATH"] != __import__("os").environ.get("PATH", "")


def test_pinned_env_path_hides_a_binary_installed_next_to_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Homebrew installs `git` and `qmd` into the same `bin/` directory, so
    pinning `PATH` to git's own parent directory — as this used to do — hands
    the child every neighbour in that directory too, `qmd` included.
    Reproduced without relying on the real machine's layout: a throwaway
    directory holding both a `git` shim and a `qmd` shim, put first on the
    ambient `PATH` so `shutil.which("git")` resolves *this* one.
    """
    fake_dir = tmp_path / "fake-homebrew-bin"
    fake_dir.mkdir()
    fake_git = fake_dir / "git"
    fake_git.write_text('#!/bin/sh\nexec /usr/bin/git "$@"\n')
    fake_git.chmod(0o755)
    fake_qmd = fake_dir / "qmd"
    fake_qmd.write_text("#!/bin/sh\nexit 0\n")
    fake_qmd.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    env = pinned_env(
        home=tmp_path / "home",
        config_dir=tmp_path / "cfg",
        data_dir=tmp_path / "data",
        agent_config_dir=tmp_path / "claude",
    )

    assert shutil.which("git", path=env["PATH"]) is not None
    assert shutil.which("qmd", path=env["PATH"]) is None, (
        f"the golden child's PATH ({env['PATH']!r}) still resolves a qmd shim living next to git"
    )


def test_normalise_run_replaces_every_channel() -> None:
    run = HookRun(stdout="a /tmp/x b", stderr="/tmp/x", exit_code=0)

    out = normalise_run(run, (("/tmp/x", "<TMP>"),))

    assert out == HookRun(stdout="a <TMP> b", stderr="<TMP>", exit_code=0)


def test_normalise_run_applies_rules_in_order() -> None:
    run = HookRun(stdout="abc", stderr="", exit_code=0)

    out = normalise_run(run, (("abc", "x"), ("x", "y")))

    assert out.stdout == "y"


def test_assert_golden_passes_on_an_exact_match(tmp_path: Path) -> None:
    run = HookRun(stdout="o", stderr="e", exit_code=2)
    path = golden_path("demo", "case", root=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"exit_code": 2, "stderr": "e", "stdout": "o"}, indent=2, ensure_ascii=False)
        + "\n"
    )

    assert_golden("demo", "case", run, root=tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [("stdout", "o!"), ("stderr", "e!"), ("exit_code", 0)],
)
def test_assert_golden_fails_when_any_single_channel_differs(
    tmp_path: Path, field: str, value: object
) -> None:
    """One byte on any channel is a failure — a golden without stderr does not
    cover the hook that refuses through it."""
    path = golden_path("demo", "case", root=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"exit_code": 2, "stderr": "e", "stdout": "o"}, indent=2, ensure_ascii=False)
        + "\n"
    )
    fields: dict[str, object] = {"stdout": "o", "stderr": "e", "exit_code": 2}
    fields[field] = value

    with pytest.raises(AssertionError, match="demo/case"):
        assert_golden("demo", "case", HookRun(**fields), root=tmp_path)  # type: ignore[arg-type]


def test_assert_golden_fails_when_the_golden_was_never_captured(tmp_path: Path) -> None:
    """A hook whose golden file was never captured was never migrated safely,
    so a missing file is a failure and never a silent capture."""
    with pytest.raises(AssertionError, match="never captured"):
        assert_golden("demo", "missing", HookRun(stdout="", stderr="", exit_code=0), root=tmp_path)


def test_assert_golden_captures_only_under_the_explicit_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LH_CAPTURE_GOLDENS", "1")

    assert_golden("demo", "fresh", HookRun(stdout="o", stderr="e", exit_code=2), root=tmp_path)

    written = json.loads(golden_path("demo", "fresh", root=tmp_path).read_text())
    assert written == {"exit_code": 2, "stderr": "e", "stdout": "o"}


def test_golden_files_are_utf8_json_with_a_trailing_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stored form is a diffable text file, so a review can read what a
    migration changed instead of an opaque blob."""
    monkeypatch.setenv("LH_CAPTURE_GOLDENS", "1")

    assert_golden("demo", "utf8", HookRun(stdout="ñ ⚠️", stderr="", exit_code=0), root=tmp_path)

    raw = golden_path("demo", "utf8", root=tmp_path).read_bytes()
    assert raw.endswith(b"\n")
    assert "ñ ⚠️" in raw.decode()


def test_run_builtin_uses_the_running_interpreter() -> None:
    """The hook must run under the interpreter the tests run under: a system
    python without the package installed would capture an ImportError golden."""
    import inspect

    from tests.unit.hooks.builtins import _goldens

    assert "sys.executable" in inspect.getsource(_goldens.run_builtin)
    assert sys.executable
