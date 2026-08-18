"""A project identity that does not change when the checkout moves.

The distilled memory for a repository is keyed by the absolute path of the
checkout, so the same repository on two machines produces two keys:

    -Users-lazynet-repos-lazy-lazy-ansible     (macOS)
    -home-lazynet-repos-lazy-lazy-ansible      (Linux)

Two directories, and the second machine starts with empty memory while looking
exactly like a repository nobody has ever worked in.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_real_ssh_config(monkeypatch, tmp_path: Path):
    """Point the alias lookup at nothing by default.

    Reading the developer's `~/.ssh/config` makes every assertion here depend
    on that machine — the failure mode this file exists to remove, reappearing
    in its own tests.
    """
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "nohome"))


def _repo(tmp_path: Path, remote: str | None = None) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    if remote is not None:
        (root / ".git" / "config").write_text(
            "[core]\n\trepositoryformatversion = 0\n"
            f'[remote "origin"]\n\turl = {remote}\n\tfetch = +refs/heads/*\n'
        )
    return root


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("git@github.com:lazynet/lazy-harness.git", "github.com/lazynet/lazy-harness"),
        ("https://github.com/lazynet/lazy-harness.git", "github.com/lazynet/lazy-harness"),
        ("https://github.com/lazynet/lazy-harness", "github.com/lazynet/lazy-harness"),
        ("ssh://git@git.lazy.net.ar:2222/lazy/thing.git", "git.lazy.net.ar/lazy/thing"),
        ("git://example.org/a/b.git", "example.org/a/b"),
    ],
)
def test_the_key_is_the_normalised_remote(tmp_path: Path, remote: str, expected: str) -> None:
    """Every URL form for one repository has to land on one key, or the two
    machines that cloned it differently still disagree."""
    from lazy_harness.core.project_identity import project_key

    assert project_key(_repo(tmp_path, remote)) == expected


def test_the_key_is_the_same_from_a_subdirectory(tmp_path: Path) -> None:
    from lazy_harness.core.project_identity import project_key

    root = _repo(tmp_path, "git@github.com:lazynet/x.git")
    deep = root / "src" / "pkg"
    deep.mkdir(parents=True)

    assert project_key(deep) == project_key(root)


def test_a_linked_worktree_resolves_to_the_main_checkout(tmp_path: Path) -> None:
    """Distilled memory outlives any one worktree; keying it per worktree
    strands it when the worktree is removed."""
    from lazy_harness.core.project_identity import project_key

    root = _repo(tmp_path, "git@github.com:lazynet/x.git")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {root}/.git/worktrees/wt\n")

    assert project_key(wt) == "github.com/lazynet/x"


def test_a_repository_without_a_remote_is_local_and_says_so(tmp_path: Path) -> None:
    """No remote means nothing to share against. The key stays machine-local
    and is spelled that way, so an unshared project is visible rather than
    looking like a sharing failure."""
    from lazy_harness.core.project_identity import project_key

    root = _repo(tmp_path, remote=None)
    key = project_key(root)

    assert key.startswith("local/")
    assert "repo" in key


def test_a_directory_outside_any_repository_is_local(tmp_path: Path) -> None:
    from lazy_harness.core.project_identity import project_key

    key = project_key(tmp_path / "not-a-repo")

    assert key.startswith("local/")


def test_the_key_never_escapes_its_root(tmp_path: Path) -> None:
    """The key becomes a directory name. A remote is remote-controlled data."""
    from lazy_harness.core.project_identity import project_key

    root = _repo(tmp_path, "https://example.org/../../etc/passwd")
    key = project_key(root)

    assert ".." not in key.split("/")


def test_origin_wins_over_another_remote(tmp_path: Path) -> None:
    """A fork adds `upstream`; the identity has to stay the user's own clone or
    two people's memory for different repos would merge."""
    from lazy_harness.core.project_identity import project_key

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text(
        '[remote "upstream"]\n\turl = git@github.com:upstream/x.git\n'
        '[remote "origin"]\n\turl = git@github.com:me/x.git\n'
    )

    assert project_key(root) == "github.com/me/x"


def test_a_single_non_origin_remote_is_used(tmp_path: Path) -> None:
    from lazy_harness.core.project_identity import project_key

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text('[remote "gitea"]\n\turl = git@h.example:g/p.git\n')

    assert project_key(root) == "h.example/g/p"


def test_an_unreadable_git_config_falls_back_to_local(tmp_path: Path) -> None:
    """Degrade rather than raise: this runs on the Stop path."""
    from lazy_harness.core.project_identity import project_key

    root = _repo(tmp_path, "git@github.com:lazynet/x.git")
    (root / ".git" / "config").write_text("this is not { valid ini [[[\n")

    assert project_key(root).startswith("local/")


def test_the_key_does_not_shell_out(tmp_path: Path, monkeypatch) -> None:
    """`project_key` runs inside hooks on the Stop path, where the existing
    code deliberately reads `.git` rather than spawning git."""
    import subprocess

    from lazy_harness.core.project_identity import project_key

    def forbidden(*args, **kwargs):
        raise AssertionError("project_key must not spawn a subprocess")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "check_output", forbidden)

    assert project_key(_repo(tmp_path, "git@github.com:lazynet/x.git"))


def _ssh_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "ssh_config"
    path.write_text(text)
    return path


def test_an_ssh_host_alias_resolves_to_its_real_host(tmp_path: Path) -> None:
    """Measured against the two real machines: the same repository is cloned as
    `https://github.com/...` on one and `git@lazynet.github.com:...` on the
    other, where `lazynet.github.com` is a per-account alias in `~/.ssh/config`.

    Without resolving it the two keys differ, which is precisely the divergence
    this identity exists to remove. Resolution is safe because the alias has to
    exist on any machine where that clone works at all.
    """
    from lazy_harness.core.project_identity import normalise_remote

    cfg = _ssh_config(tmp_path, "Host lazynet.github.com\n  HostName github.com\n  User git\n")

    assert (
        normalise_remote("git@lazynet.github.com:lazynet/x.git", ssh_config=cfg)
        == "github.com/lazynet/x"
    )
    assert normalise_remote("https://github.com/lazynet/x.git", ssh_config=cfg) == (
        "github.com/lazynet/x"
    )


def test_a_host_with_no_alias_is_left_alone(tmp_path: Path) -> None:
    from lazy_harness.core.project_identity import normalise_remote

    cfg = _ssh_config(tmp_path, "Host other\n  HostName elsewhere.example\n")

    assert normalise_remote("git@git.lazy.net.ar:lazy/x.git", ssh_config=cfg) == (
        "git.lazy.net.ar/lazy/x"
    )


def test_a_wildcard_host_block_is_not_treated_as_an_alias(tmp_path: Path) -> None:
    """`Host *` carries defaults, not an identity. Applying its `HostName`
    would rewrite every remote to one host."""
    from lazy_harness.core.project_identity import normalise_remote

    cfg = _ssh_config(tmp_path, "Host *\n  HostName wrong.example\n")

    assert normalise_remote("git@real.example:a/b.git", ssh_config=cfg) == "real.example/a/b"


def test_a_missing_ssh_config_is_not_an_error(tmp_path: Path) -> None:
    from lazy_harness.core.project_identity import normalise_remote

    assert normalise_remote("git@h:a/b.git", ssh_config=tmp_path / "nope") == "h/a/b"


def test_an_alias_pointing_at_an_ip_is_not_followed(tmp_path: Path) -> None:
    """Measured against a real config: `git.lazy.net.ar -> 10.50.10.141`.

    Following it would key the project by an internal address — less stable
    than the name it replaced, and different the moment the host moves.
    """
    from lazy_harness.core.project_identity import normalise_remote

    cfg = _ssh_config(tmp_path, "Host git.lazy.net.ar\n  HostName 10.50.10.141\n  Port 2222\n")

    assert normalise_remote("git@git.lazy.net.ar:lazy/x.git", ssh_config=cfg) == (
        "git.lazy.net.ar/lazy/x"
    )
