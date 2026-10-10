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
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.core.config import Config
from lazy_harness.core.logfile import default_log_dir
from lazy_harness.core.paths import data_dir, expand_path
from lazy_harness.knowledge import graph_freshness

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
    # A hook inherits its caller's PATH, and a GUI git client often lacks ~/.local/bin.
    lh = shlex.quote(shutil.which("lh") or "lh")
    return (
        f"{_POST_MERGE_BEGIN}\n"
        'if [ "$(git rev-parse --path-format=absolute --git-dir)" = '
        '"$(git rev-parse --path-format=absolute --git-common-dir)" ]; then\n'
        f"  mkdir -p {shlex.quote(str(log_dir))} || true\n"
        f"  nohup {lh} knowledge graph update --repo {shlex.quote(str(main_root))} "
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
    """Merge fresh discoveries into the persisted store and return the union.

    A stored repo whose graph is gone is dropped: discovery would never add it
    again, so keeping it only parks a deleted scratch repo in scope forever.
    """
    merged = [p for p in load_discovered() if (p / "graphify-out" / "graph.json").is_file()]
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


# -------------------------------------------------------------------- health

OK = "ok"
WARNING = "warning"
ERROR = "error"
SKIPPED = "skipped"
_SEVERITY = {OK: 0, SKIPPED: 0, WARNING: 1, ERROR: 2}

_HOOKS = (
    ("post-commit", _POST_COMMIT_MARK),
    ("post-checkout", _POST_CHECKOUT_MARK),
    ("post-merge", _POST_MERGE_BEGIN),
)
_UPDATE_RESULT = re.compile(r"^\[[^\]]*\] (?:updated|failed|skipped): (?P<rest>.*)$")
_SOURCE_FILE = re.compile(r'^\s+"source_file":\s*(".*")\s*,?\s*$')
_TOP_LEVEL_KEY = re.compile(r'^  "[^"]+":')
_NODES_OPEN = re.compile(r'^  "nodes":\s*\[')
# A real graph.json was 417 MB with 6.2M indented lines: read it line by line,
# never whole. A line this long means the layout is not the indented one.
_MAX_LINE = 1 << 20
_COMPACT_LIMIT = 64 << 20
_LISTED_DIRS = 5


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class RepoHealth:
    path: str
    discovered: bool
    status: str
    checks: list[HealthCheck]


@dataclass(frozen=True)
class GraphHealth:
    repos: list[RepoHealth]
    extensions: HealthCheck | None
    error: str = ""


def _hooks_path_dir(root: Path, main_root: Path) -> Path | None:
    configured = _git(root, "config", "--get", "core.hooksPath", check_codes=(0, 1))
    if configured is None or not configured.strip():
        return None
    path = Path(os.path.expanduser(configured.strip()))
    return path if path.is_absolute() else main_root / path


def check_hooks(root: Path) -> list[HealthCheck]:
    """Problems with the three hooks that keep the graph fresh; empty when sound.

    A hook is sound when its marked block sits in `<common-dir>/hooks` and git
    would actually run it: with `core.hooksPath` set (globally here, to a shared
    dispatcher), a name the directory does not carry is never forwarded.
    """
    common = git_common_dir(root)
    if common is None:
        return [HealthCheck("hooks", ERROR, "not a git repository")]
    hooks = common / "hooks"
    problems: list[HealthCheck] = []
    for name, mark in _HOOKS:
        try:
            present = mark in (hooks / name).read_text()
        except OSError:
            present = False
        if not present:
            problems.append(HealthCheck("hooks", ERROR, f"{name} missing in {hooks}"))
    forwarded = _hooks_path_dir(root, _main_root(root, common))
    if forwarded is not None:
        for name, _ in _HOOKS:
            if not (forwarded / name).exists():
                detail = f"{name} not forwarded by core.hooksPath ({forwarded})"
                problems.append(HealthCheck("hooks", ERROR, detail))
    return problems


def _age(seconds: float) -> str:
    seconds = max(seconds, 0)
    days, rest = divmod(int(seconds), 86400)
    hours = rest // 3600
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h"
    return f"{rest // 60}m"


def check_freshness(root: Path) -> list[HealthCheck]:
    graph = root / "graphify-out" / "graph.json"
    try:
        built = graph.stat().st_mtime
    except OSError:
        return [HealthCheck("freshness", WARNING, "no graph yet (graphify-out/graph.json)")]
    if graph_freshness.is_fresh(root) is not False:
        return []
    last = graph_freshness.last_code_commit_ts(root)
    gap = f", last code commit {_age(last - built)} newer" if last is not None else ""
    return [HealthCheck("freshness", WARNING, f"stale graph{gap}")]


def check_last_update(root: Path, log_path: Path) -> list[HealthCheck]:
    """The newest `updated/failed/skipped` line for `root`; a non-success is a warning."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    prefix = str(root)
    last: str | None = None
    for line in text.splitlines():
        match = _UPDATE_RESULT.match(line)
        if match is None:
            continue
        rest = match.group("rest")
        if rest == prefix or rest.startswith((f"{prefix}:", f"{prefix} (")):
            last = line.strip()
    if last is None or " updated: " in last:
        return []
    return [HealthCheck("last update", WARNING, last)]


def _node_source_files(graph: Path):  # noqa: ANN202 — a generator of str
    """`source_file` of every node, streamed; edges carry the key too and are skipped."""
    in_nodes = False
    seen_nodes = False
    with graph.open(encoding="utf-8") as f:
        while True:
            line = f.readline(_MAX_LINE)
            if not line:
                break
            if len(line) >= _MAX_LINE and not line.endswith("\n"):
                break
            if not in_nodes:
                if _NODES_OPEN.match(line):
                    in_nodes = seen_nodes = True
                continue
            if _TOP_LEVEL_KEY.match(line):
                return
            match = _SOURCE_FILE.match(line)
            if match is not None:
                yield json.loads(match.group(1))
    if seen_nodes:
        return
    if graph.stat().st_size > _COMPACT_LIMIT:
        raise ValueError("graph.json is not in the indented layout and is too large to load")
    with graph.open(encoding="utf-8") as f:
        data = json.load(f)
    for node in data.get("nodes", []) if isinstance(data, dict) else []:
        if isinstance(node, dict) and isinstance(node.get("source_file"), str):
            yield node["source_file"]


def _relative_parts(source: str, root: Path) -> tuple[str, ...] | None:
    path = Path(source)
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            return None
    return path.parts


def _ignored_dirs(root: Path, dirs: list[str]) -> set[str] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-z", "--no-index", "--stdin"],
            input="\0".join(dirs) + "\0",
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode not in (0, 1):
        return None
    return {p for p in result.stdout.split("\0") if p}


def check_ignored_in_graph(root: Path) -> list[HealthCheck]:
    """Top-level directories git ignores that the graph still has nodes from."""
    graph = root / "graphify-out" / "graph.json"
    if not graph.is_file():
        return []
    counts: dict[str, int] = {}
    try:
        for source in _node_source_files(graph):
            parts = _relative_parts(source, root)
            if parts is not None and len(parts) > 1:
                top = f"{parts[0]}/"
                counts[top] = counts.get(top, 0) + 1
    except (OSError, ValueError) as e:
        return [HealthCheck("ignored paths", WARNING, f"could not scan graph.json: {e}")]
    if not counts:
        return []
    ignored = _ignored_dirs(root, sorted(counts))
    if ignored is None:
        return [HealthCheck("ignored paths", WARNING, "could not ask git which paths are ignored")]
    hits = sorted(((d, counts[d]) for d in ignored if d in counts), key=lambda x: (-x[1], x[0]))
    if not hits:
        return []
    listed = ", ".join(f"{d} ({n} nodes)" for d, n in hits[:_LISTED_DIRS])
    if len(hits) > _LISTED_DIRS:
        listed += f", +{len(hits) - _LISTED_DIRS} more"
    return [HealthCheck("ignored paths", WARNING, f"graph indexes ignored paths: {listed}")]


_EXTENSIONS_PROBE = (
    "import json, graphify.detect as d; print(json.dumps(sorted(d.CODE_EXTENSIONS)))"
)


def _installed_extensions() -> frozenset[str] | str:
    """graphify's `CODE_EXTENSIONS`, or why they could not be read."""
    exe = shutil.which("graphify")
    if exe is None:
        return "graphify not on PATH"
    try:
        with open(exe, "rb") as f:
            first = f.readline(512)
    except OSError as e:
        return f"cannot read {exe}: {e}"
    if not first.startswith(b"#!"):
        return f"{exe} has no interpreter line"
    try:
        interpreter = shlex.split(first[2:].decode("utf-8", errors="replace"))
        result = subprocess.run(
            [*interpreter, "-c", _EXTENSIONS_PROBE],
            capture_output=True,
            text=True,
            timeout=_GRAPHIFY_INSTALL_TIMEOUT,
        )
        if result.returncode != 0:
            return f"graphify's interpreter exited {result.returncode}"
        found = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return f"could not read graphify's CODE_EXTENSIONS: {e}"
    if not isinstance(found, list) or not all(isinstance(x, str) for x in found):
        return "graphify's CODE_EXTENSIONS had an unexpected shape"
    return frozenset(found)


def check_code_extensions() -> HealthCheck:
    """Our vendored `CODE_EXTENSIONS` against the installed graphify's, once."""
    name = "code extensions"
    installed = _installed_extensions()
    if isinstance(installed, str):
        return HealthCheck(name, SKIPPED, installed)
    ours = graph_freshness.CODE_EXTENSIONS
    if installed == ours:
        return HealthCheck(name, OK, f"{len(ours)} extensions match the installed graphify")
    new = ", ".join(sorted(installed - ours)) or "none"
    gone = ", ".join(sorted(ours - installed)) or "none"
    return HealthCheck(
        name,
        WARNING,
        f"drift from the installed graphify: new {new}; no longer indexed {gone} "
        "(update graph_freshness.CODE_EXTENSIONS)",
    )


def _worst(checks: Sequence[HealthCheck]) -> str:
    return max((c.status for c in checks), key=lambda s: _SEVERITY[s], default=OK)


def _repo_health(entry: ScopedRepo, log_path: Path) -> RepoHealth:
    root = entry.path
    if not root.is_dir():
        checks = [HealthCheck("repo", ERROR, f"path missing: {root}")]
        return RepoHealth(str(root), entry.discovered, ERROR, checks)
    probes: list[tuple[str, Callable[[], list[HealthCheck]]]] = [
        ("hooks", lambda: check_hooks(root)),
        ("freshness", lambda: check_freshness(root)),
        ("last update", lambda: check_last_update(root, log_path)),
        ("ignored paths", lambda: check_ignored_in_graph(root)),
    ]
    problems: list[HealthCheck] = []
    for name, probe in probes:
        try:
            problems.extend(probe())
        except Exception as e:  # noqa: BLE001 — doctor reports a broken repo, never dies on it
            problems.append(HealthCheck(name, ERROR, f"check crashed: {e}"))
    if not problems:
        problems = [HealthCheck("graph", OK, "hooks, freshness, last update and sources are clean")]
    return RepoHealth(str(root), entry.discovered, _worst(problems), problems)


def collect_graph_health(cfg: Config, *, log_path: Path | None = None) -> GraphHealth:
    """What the harness could not fix, per repo in scope, plus one extensions line.

    Read-only: discovered repos come from the store `lh knowledge graph update`
    keeps, not from a fresh scan of the metrics.
    """
    log = log_path or default_log_dir() / "graphify-update.log"
    try:
        registered = [expand_path(entry) for entry in cfg.knowledge.structure.repos]
        scoped = scope(registered, load_discovered())
        repos = [_repo_health(entry, log) for entry in scoped]
        extensions = check_code_extensions() if repos else None
    except Exception as e:  # noqa: BLE001 — doctor reports a broken collector, never dies on it
        return GraphHealth(repos=[], extensions=None, error=f"{type(e).__name__}: {e}")
    return GraphHealth(repos=repos, extensions=extensions)
