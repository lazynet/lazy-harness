"""Tests for the shared scheduler PATH resolver."""

from __future__ import annotations


def test_resolved_path_prepends_local_bin(monkeypatch, tmp_path) -> None:
    """`uv tool install` puts `lh` in ~/.local/bin, and a scheduled unit
    inherits nothing from a login shell."""
    from lazy_harness.scheduler import paths

    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    resolved = paths.resolved_path()
    assert resolved.split(":")[0] == str(local_bin)


def test_resolved_path_drops_directories_that_do_not_exist(monkeypatch, tmp_path) -> None:
    """A unit file carrying dead entries is noise, and PATH is the single most
    common reason a scheduled job fails."""
    from lazy_harness.scheduler import paths

    real = tmp_path / "real"
    real.mkdir()
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("PATH", f"{real}:{tmp_path / 'ghost'}")

    assert str(tmp_path / "ghost") not in paths.resolved_path().split(":")
    assert str(real) in paths.resolved_path().split(":")


def test_resolved_path_does_not_duplicate_local_bin(monkeypatch, tmp_path) -> None:
    from lazy_harness.scheduler import paths

    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("PATH", f"{local_bin}:/usr/bin")

    assert paths.resolved_path().split(":").count(str(local_bin)) == 1


def test_resolved_path_falls_back_when_path_is_unset(monkeypatch, tmp_path) -> None:
    """Paired smoke test for the default-resolution branch."""
    from lazy_harness.scheduler import paths

    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("PATH", raising=False)

    resolved = paths.resolved_path()
    assert resolved
    assert "/usr/bin" in resolved or "/bin" in resolved


def test_resolved_path_drops_the_invoking_virtualenv(monkeypatch, tmp_path) -> None:
    """A unit file must not carry the interpreter that generated it.

    Running `lh scheduler install` under `uv run` from a worktree put that
    worktree's `.venv/bin` into the generated PATH, so the deployed job would
    depend on a checkout that gets deleted at cleanup. A pytest tmpdir reached
    a real crontab the same way.
    """
    from lazy_harness.scheduler import paths

    venv = tmp_path / "repo" / ".venv" / "bin"
    venv.mkdir(parents=True)
    real = tmp_path / "usr" / "bin"
    real.mkdir(parents=True)

    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("PATH", f"{venv}:{real}")
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "repo" / ".venv"))

    entries = paths.resolved_path().split(":")
    assert str(venv) not in entries
    assert str(real) in entries

