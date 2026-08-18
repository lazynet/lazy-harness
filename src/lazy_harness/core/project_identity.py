"""A project identity that survives moving between machines.

Distilled memory is keyed by the absolute path of the checkout, so the same
repository cloned to `/Users/...` and `/home/...` produces two keys and two
directories. The second machine then starts with empty memory while looking
exactly like a repository nobody has worked in — the failure is silent, which
is what makes it expensive.

The key here is the repository's own identity: its normalised remote. A
checkout with no remote has nothing to be shared against, and says so with a
`local/` prefix rather than pretending.

Nothing in this module spawns a subprocess. It is called from hooks on the
Stop path, where the surrounding code already reads `.git` directly for the
same reason.
"""

from __future__ import annotations

import configparser
import ipaddress
import re
from pathlib import Path

LOCAL_PREFIX = "local"

# `scheme://user@host:port/path`, `user@host:path`, or a bare path.
_SCP_LIKE = re.compile(r"^(?:(?P<user>[^@/]+)@)?(?P<host>[^:/]+):(?P<path>.+)$")
_URL_LIKE = re.compile(r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*)://(?P<rest>.*)$")
_URL_SECTION = re.compile(r'^url\s+"(?P<base>.*)"$')


def main_repo_root(cwd: Path) -> Path | None:
    """Main working tree for `cwd`, or None outside a repository.

    A linked worktree's `.git` is a file pointing at
    `<repo>/.git/worktrees/<name>`, so the main checkout is recoverable
    without asking git.
    """
    for directory in (cwd, *cwd.parents):
        dot_git = directory / ".git"
        if dot_git.is_dir():
            return directory
        if not dot_git.is_file():
            continue
        try:
            pointer = dot_git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not pointer.startswith("gitdir:"):
            return None
        gitdir = Path(pointer[len("gitdir:") :].strip())
        # `<repo>/.git/worktrees/<name>` -> `<repo>`
        for parent in gitdir.parents:
            if parent.name == ".git":
                return parent.parent
        return None
    return None


def _is_ip_literal(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _ssh_host_aliases(ssh_config: Path | None) -> dict[str, str]:
    """`Host` -> `HostName` for literal, non-wildcard aliases.

    Only exact hosts: `Host *` carries defaults rather than an identity, and
    applying its `HostName` would rewrite every remote to one host.

    `Include` directives are not followed. An alias reached only through an
    include resolves to itself, which keeps the key stable per machine but not
    across them — the check in `lh doctor` is what surfaces that.
    """
    if ssh_config is None:
        ssh_config = Path.home() / ".ssh" / "config"
    try:
        text = ssh_config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    aliases: dict[str, str] = {}
    current: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(" ")
        key = key.rstrip("=").lower()
        value = value.strip().lstrip("=").strip()
        if key == "host":
            current = [h for h in value.split() if not any(c in h for c in "*?!")]
        elif key == "hostname" and value:
            if _is_ip_literal(value):
                # `git.lazy.net.ar -> 10.50.10.141` is a real alias in a real
                # config. Following it would key the project by an internal
                # address — less stable than the name it replaced, and
                # different the moment the host moves.
                continue
            for host in current:
                aliases.setdefault(host, value)
    return aliases


def _insteadof_aliases(git_config: Path | None = None) -> dict[str, str]:
    """`shorthand` -> `base` for every `url.<base>.insteadOf`.

    Git stores a remote URL exactly as it was typed and expands `insteadOf` at
    transport time, so a clone made with a shorthand keeps that spelling in
    `.git/config` forever. `git remote get-url` hides this by expanding on
    read; the file is what the identity has to be taken from.

    `pushInsteadOf` is deliberately absent: it says where a push goes, not what
    the repository is, and the two differ on purpose behind a read-only mirror.

    Only the user-level files are read, and a key repeated across them takes
    its last value rather than accumulating as git would. An `insteadOf` set
    per-repository resolves to itself, which keeps the key stable per machine
    but not across them — the same limit, and the same reason, as `Include`.
    """
    if git_config is None:
        home = Path.home()
        paths = [home / ".config" / "git" / "config", home / ".gitconfig"]
    else:
        paths = [git_config]

    aliases: dict[str, str] = {}
    for path in paths:
        # One parser per file: a malformed `~/.gitconfig` must not take the
        # XDG one down with it. Same `strict`/`interpolation` reasoning as
        # `_remote_url`, plus `allow_no_value` because git allows a bare key.
        parser = configparser.ConfigParser(strict=False, interpolation=None, allow_no_value=True)
        try:
            parser.read(path)
        except (OSError, configparser.Error, UnicodeDecodeError):
            continue
        for section in parser.sections():
            match = _URL_SECTION.match(section.strip())
            if match is None:
                continue
            base = match.group("base")
            shorthand = (parser.get(section, "insteadof", fallback="") or "").strip()
            # An empty shorthand is a prefix of every URL: honouring it would
            # rewrite every remote on the machine to one host.
            if base and shorthand:
                aliases[shorthand] = base
    return aliases


def _apply_insteadof(url: str, aliases: dict[str, str]) -> str:
    """`url` with its longest matching shorthand expanded.

    Longest wins because git resolves it that way, and because a general
    prefix and a more specific one legitimately coexist — picking the first
    match would make the result depend on the order of the file.
    """
    matched: str | None = None
    for shorthand in aliases:
        if url.startswith(shorthand) and (matched is None or len(shorthand) > len(matched)):
            matched = shorthand
    if matched is None:
        return url
    return aliases[matched] + url[len(matched) :]


def normalise_remote(
    url: str, *, ssh_config: Path | None = None, git_config: Path | None = None
) -> str:
    """`host/path` for a remote URL, with no scheme, credentials or `.git`.

    Every URL form for one repository has to land on one string, or two
    machines that cloned it differently still disagree about its identity.
    """
    url = url.strip()
    if not url:
        return ""

    # Before parsing: an `insteadOf` shorthand names no host of its own, so a
    # URL that still carries it has nothing for the rest of this function or
    # the SSH lookup to resolve.
    url = _apply_insteadof(url, _insteadof_aliases(git_config))

    match = _URL_LIKE.match(url)
    if match:
        rest = match.group("rest")
        rest = rest.split("@", 1)[-1]  # drop credentials
        host, _, path = rest.partition("/")
        host = host.split(":", 1)[0]  # drop the port
    else:
        scp = _SCP_LIKE.match(url)
        if scp:
            host, path = scp.group("host"), scp.group("path")
        else:
            return ""

    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]

    # An SSH host alias is a local name for a real host. The same repository is
    # cloned as `https://github.com/...` on one machine and
    # `git@lazynet.github.com:...` on another, and without this the two keys
    # differ — which is the divergence this identity exists to remove.
    host = _ssh_host_aliases(ssh_config).get(host, host)

    parts = [p for p in (host, *path.split("/")) if p and p not in (".", "..")]
    return "/".join(parts)


def _remote_url(root: Path) -> str:
    """The `origin` remote's URL, or the only remote's if there is no origin.

    A fork carries an `upstream` too; taking it would merge two people's memory
    for what is, to them, two different repositories.
    """
    # `strict=False` because git's format allows a key to repeat — `fetch` and
    # `push` legitimately, and plugins write their own duplicates. Strict
    # parsing raises on the whole file, so one repeated line silently demotes a
    # repository with a perfectly good `origin` to `local/`.
    # `interpolation=None` because `%` is legal in a URL and is configparser's
    # sigil; left on, it raises from `get`, outside the guard below.
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read(root / ".git" / "config")
    except (OSError, configparser.Error, UnicodeDecodeError):
        return ""

    remotes: dict[str, str] = {}
    for section in parser.sections():
        name = section.strip()
        if not name.startswith("remote "):
            continue
        label = name[len("remote ") :].strip().strip('"')
        url = parser.get(section, "url", fallback="").strip()
        if url:
            remotes[label] = url

    if "origin" in remotes:
        return remotes["origin"]
    if len(remotes) == 1:
        return next(iter(remotes.values()))
    return ""


def _local_key(cwd: Path) -> str:
    """A machine-local key, spelled so it is visibly not shared."""
    root = main_repo_root(cwd) or cwd
    return f"{LOCAL_PREFIX}/{root.name or 'root'}"


def project_key(
    cwd: Path, *, ssh_config: Path | None = None, git_config: Path | None = None
) -> str:
    """The stable identity of the project containing `cwd`.

    `host/owner/name` when the repository has a remote; `local/<name>`
    otherwise. Never absolute, never machine-specific, and never escapes the
    directory it will be created under.
    """
    root = main_repo_root(cwd)
    if root is None:
        return _local_key(cwd)
    key = normalise_remote(_remote_url(root), ssh_config=ssh_config, git_config=git_config)
    return key or _local_key(cwd)
