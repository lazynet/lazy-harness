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


def test_a_git_config_with_duplicate_options_still_yields_its_remote(tmp_path: Path) -> None:
    """Git's config format allows a key to repeat; `configparser` does not.

    Measured against a real checkout: `devops-tf-infra` carries a
    `github-pr-owner-number` written twice under one branch section by a
    plugin, plus the ordinary repeated `fetch` lines. Strict parsing raises
    `DuplicateOptionError` on the whole file, so a repository with a perfectly
    good `origin` was keyed `local/` and its memory never left the machine —
    silently, which is the expensive part.
    """
    from lazy_harness.core.project_identity import project_key

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text(
        '[remote "origin"]\n'
        "\turl = git@github.com:o/x.git\n"
        "\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
        "\tfetch = +refs/pull/*/head:refs/remotes/origin/pr/*\n"
        '[branch "feature/DO-251"]\n'
        "\tgithub-pr-owner-number = o#1\n"
        "\tgithub-pr-owner-number = o#2\n"
    )

    assert project_key(root) == "github.com/o/x"


def test_a_percent_in_a_remote_url_is_not_interpolated(tmp_path: Path) -> None:
    """`%` is legal in a URL and is `configparser`'s interpolation sigil.

    Left on, it raises and the repository silently becomes `local/` — the same
    failure as the duplicate-option one, reached from a different direction.
    """
    from lazy_harness.core.project_identity import project_key

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = https://user%40host@example.org/o/x.git\n'
    )

    assert project_key(root) == "example.org/o/x"


def _git_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "gitconfig"
    path.write_text(text)
    return path


def test_an_insteadof_shorthand_resolves_to_the_host_it_stands_for(tmp_path: Path) -> None:
    """Measured against a real checkout: `lazy-desktop-manager` carries
    `url = forge:lazy/lazy-desktop-manager.git`, because git stores the URL as
    it was typed and applies `url.*.insteadOf` at transport time.

    `forge` is not an SSH alias, so nothing else resolves it and the repository
    opened a third namespace of its own — a split the knowledge store had to
    fold back by hand.
    """
    from lazy_harness.core.project_identity import normalise_remote

    cfg = _git_config(tmp_path, '[url "git@git.lazy.net.ar:"]\n\tinsteadOf = forge:\n')

    assert normalise_remote("forge:lazy/lazy-desktop-manager.git", git_config=cfg) == (
        "git.lazy.net.ar/lazy/lazy-desktop-manager"
    )


def test_the_longest_matching_insteadof_wins(tmp_path: Path) -> None:
    """Git resolves the longest `insteadOf` that matches, so a general prefix
    and a more specific one can coexist. Taking the first match instead would
    make the result depend on the order of the file.
    """
    from lazy_harness.core.project_identity import normalise_remote

    cfg = _git_config(
        tmp_path,
        '[url "git@generic.example:"]\n\tinsteadOf = forge:\n'
        '[url "git@specific.example:mirror/"]\n\tinsteadOf = forge:lazy/\n',
    )

    assert normalise_remote("forge:lazy/x.git", git_config=cfg) == "specific.example/mirror/x"


def test_a_push_insteadof_does_not_change_the_identity(tmp_path: Path) -> None:
    """`pushInsteadOf` rewrites where a push goes, not what the repository is.

    Applying it would key a repository by the server it publishes to rather
    than the one it was cloned from, which are deliberately different when a
    read-only mirror is in play.
    """
    from lazy_harness.core.project_identity import normalise_remote

    cfg = _git_config(tmp_path, '[url "git@push.example:"]\n\tpushInsteadOf = forge:\n')

    assert normalise_remote("forge:a/b.git", git_config=cfg) == "forge/a/b"


def test_an_insteadof_is_applied_before_the_ssh_alias(tmp_path: Path) -> None:
    """The two rewrites chain: the shorthand names a host that `~/.ssh/config`
    then renames. Resolving them the other way round leaves the shorthand
    unmatched, because `forge` is not a host any SSH config knows.
    """
    from lazy_harness.core.project_identity import normalise_remote

    git_cfg = _git_config(tmp_path, '[url "git@alias.example:"]\n\tinsteadOf = forge:\n')
    ssh_cfg = _ssh_config(tmp_path, "Host alias.example\n  HostName real.example\n")

    assert normalise_remote("forge:a/b.git", ssh_config=ssh_cfg, git_config=git_cfg) == (
        "real.example/a/b"
    )


def test_a_missing_git_config_is_not_an_error(tmp_path: Path) -> None:
    from lazy_harness.core.project_identity import normalise_remote

    assert normalise_remote("git@h:a/b.git", git_config=tmp_path / "nope") == "h/a/b"


def test_a_git_config_with_duplicate_options_still_yields_its_aliases(tmp_path: Path) -> None:
    """The same parsing hazard as `.git/config`, reached from the user's own
    file: one repeated key must not discard every `insteadOf` on the machine.
    """
    from lazy_harness.core.project_identity import normalise_remote

    cfg = _git_config(
        tmp_path,
        '[user]\n\tname = a\n\tname = b\n[url "git@git.lazy.net.ar:"]\n\tinsteadOf = forge:\n',
    )

    assert normalise_remote("forge:a/b.git", git_config=cfg) == "git.lazy.net.ar/a/b"


def test_a_url_section_with_no_insteadof_is_ignored(tmp_path: Path) -> None:
    """`[url]` also carries unrelated settings. A section without an
    `insteadOf` describes no shorthand and must not rewrite anything."""
    from lazy_harness.core.project_identity import normalise_remote

    cfg = _git_config(tmp_path, '[url "git@git.lazy.net.ar:"]\n\tanything = else\n')

    assert normalise_remote("https://github.com/o/x.git", git_config=cfg) == "github.com/o/x"


def test_project_key_resolves_an_insteadof_shorthand(tmp_path: Path) -> None:
    """The whole point: the shorthand and the canonical spelling of one server
    have to land on one key, or the checkout keeps a memory directory of its
    own that nothing else ever reads.
    """
    from lazy_harness.core.project_identity import project_key

    cfg = _git_config(tmp_path, '[url "git@git.lazy.net.ar:"]\n\tinsteadOf = forge:\n')

    shorthand = _repo(tmp_path / "a", "forge:lazy/x.git")
    canonical = _repo(tmp_path / "b", "git@git.lazy.net.ar:lazy/x.git")

    assert project_key(shorthand, git_config=cfg) == "git.lazy.net.ar/lazy/x"
    assert project_key(canonical, git_config=cfg) == "git.lazy.net.ar/lazy/x"


def test_an_empty_insteadof_does_not_match_everything(tmp_path: Path) -> None:
    """An empty shorthand is a prefix of every URL, so honouring it would
    rewrite every remote on the machine to one host — the `Host *` hazard in
    its git spelling.
    """
    from lazy_harness.core.project_identity import normalise_remote

    cfg = _git_config(tmp_path, '[url "git@wrong.example:"]\n\tinsteadOf =\n')

    assert normalise_remote("https://github.com/o/x.git", git_config=cfg) == "github.com/o/x"


def test_the_default_lookup_reads_the_users_own_gitconfig(tmp_path: Path) -> None:
    """Every other test here injects the path, which leaves the branch that
    actually runs in production — no argument at all — unexercised.
    """
    from lazy_harness.core.project_identity import normalise_remote

    home = tmp_path / "nohome"
    home.mkdir()
    (home / ".gitconfig").write_text('[url "git@git.lazy.net.ar:"]\n\tinsteadOf = forge:\n')

    assert normalise_remote("forge:lazy/x.git") == "git.lazy.net.ar/lazy/x"


def test_the_default_lookup_also_reads_the_xdg_gitconfig(tmp_path: Path) -> None:
    """Git reads `~/.config/git/config` too, and a machine that keeps its
    config there has no `~/.gitconfig` to find."""
    from lazy_harness.core.project_identity import normalise_remote

    xdg = tmp_path / "nohome" / ".config" / "git"
    xdg.mkdir(parents=True)
    (xdg / "config").write_text('[url "git@git.lazy.net.ar:"]\n\tinsteadOf = forge:\n')

    assert normalise_remote("forge:lazy/x.git") == "git.lazy.net.ar/lazy/x"


def test_the_users_own_gitconfig_outranks_the_xdg_one(tmp_path: Path) -> None:
    """Both files can define the same shorthand; git lets `~/.gitconfig` win.

    Reading them in the other order would resolve a repository against a
    setting the user believes they have overridden.
    """
    from lazy_harness.core.project_identity import normalise_remote

    home = tmp_path / "nohome"
    xdg = home / ".config" / "git"
    xdg.mkdir(parents=True)
    (xdg / "config").write_text('[url "git@stale.example:"]\n\tinsteadOf = forge:\n')
    (home / ".gitconfig").write_text('[url "git@current.example:"]\n\tinsteadOf = forge:\n')

    assert normalise_remote("forge:a/b.git") == "current.example/a/b"
