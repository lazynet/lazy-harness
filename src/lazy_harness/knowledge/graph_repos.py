"""Self-repair and scope for the repos whose code graph the harness keeps fresh.

Three things stopped graphs from refreshing without anyone noticing: no
`post-merge` hook (a pull or fast-forward moves HEAD without `post-commit`),
graphify's own hooks missing from the repo, and directories git ignores only
through the user's global excludes file, which graphify does not read and so
indexes (a 417 MB graph, permanently stale because every rebuild timed out).

`ensure_repo` fixes all three, idempotently, and reports what it did per
action. `scope` is the set of repos `lh knowledge graph update` walks:
registered ones plus repos the graph-assist hook has been seen working in.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.core.config import Config
from lazy_harness.core.logfile import default_log_dir
from lazy_harness.core.paths import data_dir

INSTALLED = "installed"
ALREADY = "already"
_FAILED = "failed: "

_POST_MERGE_BEGIN = "# lazy-harness graph-begin"
_POST_MERGE_END = "# lazy-harness graph-end"
_IGNORED_BEGIN = "# lazy-harness graph-ignored-begin"
_IGNORED_END = "# lazy-harness graph-ignored-end"
_POST_COMMIT_MARK = "# graphify-hook-start"
_POST_CHECKOUT_MARK = "# graphify-checkout-hook-start"

_GIT_TIMEOUT = 30
_GRAPHIFY_INSTALL_TIMEOUT = 60


@dataclass(frozen=True)
class RepoRepair:
    root: Path
    post_merge: str
    graphify_hooks: str
    ignored: str

    def changes(self) -> dict[str, str]:
        """Every action that did something or failed; `already` is silence."""
        actions = {
            "post-merge": self.post_merge,
            "graphify hooks": self.graphify_hooks,
            "ignored paths": self.ignored,
        }
        return {name: status for name, status in actions.items() if status != ALREADY}


@dataclass(frozen=True)
class ScopedRepo:
    path: Path
    discovered: bool


def _failed(why: str) -> str:
    return f"{_FAILED}{why}"


def _git(root: Path, *args: str, check_codes: Sequence[int] = (0,)) -> str | None:
    """Stdout of `git -C root <args>`, or None on a bad exit code or no git."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode not in check_codes:
        return None
    return result.stdout


def git_common_dir(root: Path) -> Path | None:
    """The directory holding hooks and info/exclude for `root`'s repository.

    The common dir, never `--git-dir`: inside a linked worktree the git dir is
    `<repo>/.git/worktrees/<name>`, which has no `hooks/` of its own.
    """
    out = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if out is None or not out.strip():
        return None
    return Path(out.strip())


def _main_root(root: Path, common: Path) -> Path:
    """The main checkout: where the graph lives and what a hook must update."""
    return common.parent if common.name == ".git" else root


def _upsert_block(text: str, begin: str, end: str, block: str) -> str:
    """`text` with the marked region replaced by `block`, or `block` appended."""
    start = text.find(begin)
    stop = text.find(end, start) if start != -1 else -1
    if start != -1 and stop != -1:
        stop_line = text.find("\n", stop)
        tail = "" if stop_line == -1 else text[stop_line + 1 :]
        return text[:start] + block + tail
    if text and not text.endswith("\n"):
        text += "\n"
    return text + block


def _strip_block(text: str, begin: str, end: str) -> str:
    start = text.find(begin)
    stop = text.find(end, start) if start != -1 else -1
    if start == -1 or stop == -1:
        return text
    stop_line = text.find("\n", stop)
    tail = "" if stop_line == -1 else text[stop_line + 1 :]
    return text[:start] + tail


# ---------------------------------------------------------------- post-merge


def _post_merge_block(main_root: Path, log_dir: Path) -> str:
    log = log_dir / "graphify-post-merge.log"
    return (
        f"{_POST_MERGE_BEGIN}\n"
        'if [ "$(git rev-parse --path-format=absolute --git-dir)" = '
        '"$(git rev-parse --path-format=absolute --git-common-dir)" ]; then\n'
        f"  mkdir -p {shlex.quote(str(log_dir))} || true\n"
        f"  nohup lh knowledge graph update --repo {shlex.quote(str(main_root))} "
        f">> {shlex.quote(str(log))} 2>&1 < /dev/null &\n"
        "fi\n"
        f"{_POST_MERGE_END}\n"
    )


def ensure_post_merge(root: Path, *, log_dir: Path | None = None) -> str:
    """Install the marked `post-merge` block that refreshes the graph after a pull.

    The block does nothing in a linked worktree (a worktree merge must not
    rebuild the whole graph) and never fails the merge: the update runs
    detached and its output goes to a log.
    """
    common = git_common_dir(root)
    if common is None:
        return _failed("not a git repository")
    hook = common / "hooks" / "post-merge"
    block = _post_merge_block(_main_root(root, common), log_dir or default_log_dir())
    try:
        current = hook.read_text() if hook.exists() else None
        base = "#!/bin/sh\n" if current is None else current
        new = _upsert_block(base, _POST_MERGE_BEGIN, _POST_MERGE_END, block)
        executable = current is not None and bool(hook.stat().st_mode & 0o100)
        if current == new and executable:
            return ALREADY
        hook.parent.mkdir(parents=True, exist_ok=True)
        if current != new:
            hook.write_text(new)
        hook.chmod(hook.stat().st_mode | 0o111)
    except OSError as e:
        return _failed(str(e))
    return INSTALLED


# ------------------------------------------------------------- graphify hooks


def _graphify_hooks_present(hooks: Path) -> bool:
    def has(name: str, mark: str) -> bool:
        try:
            return mark in (hooks / name).read_text()
        except OSError:
            return False

    return has("post-commit", _POST_COMMIT_MARK) and has("post-checkout", _POST_CHECKOUT_MARK)


def _config_override_env(key: str, value: str) -> dict[str, str]:
    """`os.environ` plus one git config entry that applies to every child git.

    Appends after any entries the caller's environment already carries rather
    than replacing them.
    """
    env = dict(os.environ)
    try:
        count = int(env.get("GIT_CONFIG_COUNT", "0") or "0")
    except ValueError:
        count = 0
    env["GIT_CONFIG_COUNT"] = str(count + 1)
    env[f"GIT_CONFIG_KEY_{count}"] = key
    env[f"GIT_CONFIG_VALUE_{count}"] = value
    return env


def ensure_graphify_hooks(root: Path) -> str:
    """Make sure graphify's `post-commit` and `post-checkout` live in the repo.

    `graphify hook install` writes where `core.hooksPath` points when it is
    set, and the global one here is a shared dispatcher: a bare run appended
    graphify's block to the dispatcher file itself and created a global
    `post-checkout` that rebuilds every repo's graph on every checkout. The
    install runs with `core.hooksPath` overridden to the repo's own hooks
    directory, which is also where the dispatcher forwards to.
    """
    common = git_common_dir(root)
    if common is None:
        return _failed("not a git repository")
    hooks = common / "hooks"
    if _graphify_hooks_present(hooks):
        return ALREADY
    exe = shutil.which("graphify")
    if exe is None:
        return _failed("graphify not on PATH")
    env = _config_override_env("core.hooksPath", str(hooks))
    try:
        result = subprocess.run(
            [exe, "hook", "install"],
            cwd=_main_root(root, common),
            env=env,
            capture_output=True,
            text=True,
            timeout=_GRAPHIFY_INSTALL_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return _failed(f"graphify hook install: {e}")
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        return _failed(lines[-1] if lines else f"graphify hook install exited {result.returncode}")
    if not _graphify_hooks_present(hooks):
        return _failed(f"graphify hook install exited 0 but left no hooks in {hooks}")
    return INSTALLED


# ------------------------------------------------------------- ignored paths


def _global_excludes_file(root: Path) -> Path:
    configured = _git(root, "config", "--path", "core.excludesfile", check_codes=(0, 1))
    if configured and configured.strip():
        return Path(configured.strip())
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "git" / "ignore"


def _global_only_ignored_dirs(root: Path) -> list[str] | None:
    """Ignored directories whose ignoring rule lives in the global excludes file.

    None when git could not answer; an empty list is a real answer.
    """
    listed = _git(
        root, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory"
    )
    if listed is None:
        return None
    dirs = sorted({p for p in listed.split("\0") if p.endswith("/")})
    if not dirs:
        return []
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-v", "-z", "--no-index", "--stdin"],
            input="\0".join(dirs) + "\0",
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode not in (0, 1):
        return None
    fields = result.stdout.split("\0")
    glob_file = _global_excludes_file(root).resolve()
    only: list[str] = []
    # `-v -z` output is four NUL-terminated fields per path: source, line, pattern, path.
    for i in range(0, len(fields) - 3, 4):
        source, path = fields[i], fields[i + 3]
        if source and Path(source).resolve() == glob_file:
            only.append(path)
    return sorted(set(only))


def ensure_ignored(root: Path) -> str:
    """Mirror global-only ignored directories into a marked block of `info/exclude`.

    Git behaves the same afterwards (those paths were already ignored); graphify
    reads `info/exclude` and stops indexing them. The block is derived afresh on
    every run, so a path removed from the global file leaves it.

    The block is taken out before asking git which rule ignores what: it would
    otherwise answer "info/exclude" for everything the block already lists and
    a stale entry could never leave.
    """
    common = git_common_dir(root)
    if common is None:
        return _failed("not a git repository")
    exclude = common / "info" / "exclude"
    try:
        original = exclude.read_text() if exclude.exists() else ""
    except OSError as e:
        return _failed(str(e))
    stripped = _strip_block(original, _IGNORED_BEGIN, _IGNORED_END)
    try:
        if stripped != original:
            exclude.write_text(stripped)
        entries = _global_only_ignored_dirs(_main_root(root, common))
        if entries is None:
            exclude.write_text(original)
            return _failed("git could not list ignored paths")
        if entries:
            block = (
                f"{_IGNORED_BEGIN}\n" + "".join(f"/{e}\n" for e in entries) + f"{_IGNORED_END}\n"
            )
            new = _upsert_block(original, _IGNORED_BEGIN, _IGNORED_END, block)
        else:
            new = stripped
        if new == original:
            if stripped != original:
                exclude.write_text(original)
            return ALREADY
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(new)
    except OSError as e:
        try:
            exclude.write_text(original)
        except OSError:
            pass
        return _failed(str(e))
    return INSTALLED


# --------------------------------------------------------------- ensure_repo


def _guarded(action: Callable[[], str]) -> str:
    try:
        return action()
    except Exception as e:  # noqa: BLE001 — one broken action must not skip the others
        return _failed(f"{type(e).__name__}: {e}")


def ensure_repo(root: Path, *, log_dir: Path | None = None) -> RepoRepair:
    """Run the three repairs for one repo. Idempotent; each reports its own result."""
    return RepoRepair(
        root=root,
        post_merge=_guarded(lambda: ensure_post_merge(root, log_dir=log_dir)),
        graphify_hooks=_guarded(lambda: ensure_graphify_hooks(root)),
        ignored=_guarded(lambda: ensure_ignored(root)),
    )


# --------------------------------------------------------------------- scope


def store_path() -> Path:
    return data_dir() / "graph-repos.json"


def load_discovered() -> list[Path]:
    """Discovered repos persisted by an earlier run; a corrupt store is empty."""
    try:
        data = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("discovered") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [Path(p) for p in items if isinstance(p, str) and p]


def _metrics_files(cfg: Config) -> list[Path]:
    """The files the graph-assist hook writes, one per profile's runtime dir."""
    from lazy_harness.hooks.builtins._shared import agent_dir_for

    files: list[Path] = []
    for profile in cfg.profiles.items:
        try:
            runtime = agent_dir_for(cfg, profile)[1]
        except Exception:  # noqa: BLE001 — an unresolvable profile contributes nothing
            continue
        path = runtime / "logs" / "graph_assist_metrics.jsonl"
        if path not in files:
            files.append(path)
    return files


def discover_repos(cfg: Config) -> list[Path]:
    """Repos with a graph that the hook has evaluated, from every profile's metrics."""
    found: list[Path] = []
    for path in _metrics_files(cfg):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in text.splitlines():
            if '"repo"' not in raw:
                continue
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            repo = line.get("repo") if isinstance(line, dict) else None
            if not isinstance(repo, str) or not repo:
                continue
            candidate = Path(repo)
            if candidate not in found and (candidate / "graphify-out" / "graph.json").is_file():
                found.append(candidate)
    return found


def refresh_discovered(cfg: Config) -> list[Path]:
    """Merge fresh discoveries into the persisted store and return the union."""
    merged = load_discovered()
    for repo in discover_repos(cfg):
        if repo not in merged:
            merged.append(repo)
    path = store_path()
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"discovered": [str(p) for p in merged]}, indent=2) + "\n")
        tmp.replace(path)
    except OSError:
        pass
    return merged


def scope(registered: Sequence[Path], discovered: Sequence[Path]) -> list[ScopedRepo]:
    """Registered repos first, then discovered ones not already registered."""
    seen: set[Path] = set()
    out: list[ScopedRepo] = []
    for paths, is_discovered in ((registered, False), (discovered, True)):
        for p in paths:
            key = p.resolve()
            if key in seen:
                continue
            seen.add(key)
            out.append(ScopedRepo(p, is_discovered))
    return out
