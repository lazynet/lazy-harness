"""Tests for the shared scheduler PATH resolver."""

from __future__ import annotations


def test_resolved_path_ignores_the_invoking_environment(monkeypatch, tmp_path) -> None:
    """The generated PATH is a property of the platform, not of the terminal.

    Reading `os.environ["PATH"]` made the unit file depend on who ran
    `lh scheduler install` and from where. On a developer's Mac that PATH
    carried pyenv shims ahead of Homebrew, so a job's `python` resolved to a
    shim in a context with no shell to initialise it; over ssh the same call
    produced five clean entries, which is why it looked correct on Linux.
    """
    from lazy_harness.scheduler import paths

    intruder = tmp_path / "intruder" / "bin"
    intruder.mkdir(parents=True)
    monkeypatch.setenv("PATH", str(intruder))

    assert str(intruder) not in paths.resolved_path().split(":")


def test_resolved_path_is_stable_across_different_environments(monkeypatch, tmp_path) -> None:
    """Two installs from two shells must produce the same unit file."""
    from lazy_harness.scheduler import paths

    shell_a = tmp_path / "a"
    shell_b = tmp_path / "b"
    for directory in (shell_a, shell_b):
        directory.mkdir()

    monkeypatch.setenv("PATH", str(shell_a))
    first = paths.resolved_path()
    monkeypatch.setenv("PATH", f"{shell_b}:/usr/bin")
    second = paths.resolved_path()

    assert first == second


def test_resolved_path_prepends_local_bin(monkeypatch, tmp_path) -> None:
    """`uv tool install` puts `lh` in ~/.local/bin.

    Unconditional, unlike the rest: this is the directory the tool installs
    itself into, so its absence when the unit is written is no evidence it
    will be absent when the unit runs.
    """
    from lazy_harness.scheduler import paths

    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))

    resolved = paths.resolved_path()
    assert resolved.split(":")[0] == str(tmp_path / ".local" / "bin")


def test_resolved_path_drops_candidates_that_do_not_exist(monkeypatch, tmp_path) -> None:
    """A unit carrying dead entries is noise, and PATH is the single most
    common reason a scheduled job fails.

    The candidate list is injected rather than asserted against the real
    filesystem: comparing `resolved_path()` to `Path(...).is_dir()` restates
    the implementation's own predicate, and passes on any host where every
    standard directory happens to exist — which is all of them.
    """
    from lazy_harness.scheduler import paths

    present = tmp_path / "present"
    present.mkdir()
    absent = tmp_path / "absent"
    monkeypatch.setattr(paths, "_STANDARD", (str(present), str(absent)))

    entries = paths.resolved_path().split(":")
    assert str(present) in entries
    assert str(absent) not in entries


def test_homebrew_is_a_candidate_on_every_platform() -> None:
    """Homebrew is the one platform-specific entry, and it is presence-gated
    rather than branched on `sys.platform` — an Intel Mac, an Apple Silicon
    Mac and a Linux box then need no separate code path.

    Asserted against the candidate list, not against the runner's filesystem:
    `/opt/homebrew/bin` never exists on a Linux runner, so a test comparing
    the two would pass there with the entry deleted from the source.
    """
    from lazy_harness.scheduler import paths

    assert "/opt/homebrew/bin" in paths._STANDARD


def test_resolved_path_never_carries_a_virtualenv(monkeypatch, tmp_path) -> None:
    """The recorded failure this resolver exists for.

    Running `lh scheduler install` under `uv run` from a worktree put that
    worktree's `.venv/bin` into the generated PATH, so the deployed job
    depended on a checkout that `/cleanup-worktree` deletes. Filtering the
    inherited PATH fixed the case that was seen; not reading it fixes the
    class.
    """
    from lazy_harness.scheduler import paths

    venv = tmp_path / "repo" / ".venv" / "bin"
    venv.mkdir(parents=True)
    monkeypatch.setenv("PATH", str(venv))
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "repo" / ".venv"))

    entries = paths.resolved_path().split(":")
    assert not any(".venv" in e for e in entries), entries


def test_resolved_path_survives_an_unset_path(monkeypatch, tmp_path) -> None:
    """Paired smoke test: nothing may read PATH, including by accident."""
    from lazy_harness.scheduler import paths

    monkeypatch.delenv("PATH", raising=False)

    resolved = paths.resolved_path()
    assert "/usr/bin" in resolved.split(":")
