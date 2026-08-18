"""Shared helpers for builtin hooks.

Behavior-preserving extraction of the `_log` and `_find_latest_session`
helpers that were copy-pasted across the builtin hooks. Hooks bind
`_log = make_log("<hook-name>")` at module level so call sites stay
identical to the historical per-module definitions.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

_TRANSCRIPT_KEYS = ("transcript_path", "transcriptPath", "input")


def make_log(hook_name: str) -> Callable[[Path, str], None]:
    """Build a fail-soft logger that prefixes lines with `<ts> <hook_name>:`."""

    def _log(log_file: Path, msg: str) -> None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().astimezone().isoformat(timespec="seconds")
            with open(log_file, "a") as f:
                f.write(f"{ts} {hook_name}: {msg}\n")
        except OSError:
            pass

    return _log


def find_latest_session(sessions_dir: Path) -> Path | None:
    """Most recently modified session JSONL in `sessions_dir`, or None."""
    if not sessions_dir.is_dir():
        return None
    jsonl_files = [p for p in sessions_dir.glob("*.jsonl") if p.is_file()]
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def _declared_transcript(payload: object) -> Path | None:
    """Transcript path as declared in the payload, without touching the filesystem."""
    if not isinstance(payload, Mapping):
        return None
    for key in _TRANSCRIPT_KEYS:
        raw = payload.get(key)
        if isinstance(raw, str) and raw:
            return Path(raw)
    return None


def transcript_from_payload(payload: object) -> Path | None:
    """Session JSONL the agent declared on stdin, or None if absent/not yet written."""
    declared = _declared_transcript(payload)
    if declared is None:
        return None
    return declared if declared.is_file() else None


def project_dir_from_payload(payload: object) -> Path | None:
    """Agent-owned per-project session dir, read from the declared transcript.

    The agent encodes the cwd into this directory name with a scheme that has
    changed across releases, so it is read here rather than recomputed. At
    SessionStart the transcript is not written yet, so only its parent is
    required to exist.
    """
    declared = _declared_transcript(payload)
    if declared is None:
        return None
    parent = declared.parent
    return parent if parent.is_dir() else None


def resolve_project_dir(
    payload: object, *, agent_dir: Path, sessions_subdir: str, cwd: Path
) -> Path:
    """Per-project session dir: the agent's own, else one derived from `cwd`.

    Only a declared dir inside the adapter's sessions root is honoured, so
    harness artifacts never escape it (ADR-032). The cwd-derived fallback
    matches agents whose encoding is a plain slash-to-dash rewrite.
    """
    sessions_root = agent_dir / (sessions_subdir or "projects")
    declared = project_dir_from_payload(payload)
    if declared is not None and declared.parent == sessions_root:
        return declared
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    return sessions_root / encoded


def _main_repo_root(cwd: Path) -> Path | None:
    """Main working tree for `cwd`, or None outside a repo.

    Read from `.git` rather than shelling out to git: a linked worktree's
    `.git` is a file pointing at `<repo>/.git/worktrees/<name>`, so the main
    checkout is recoverable without a subprocess on the Stop path.
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
        gitdir = Path(pointer.split(":", 1)[1].strip())
        if not gitdir.is_absolute():
            gitdir = (directory / gitdir).resolve()
        for parent in gitdir.parents:
            if parent.name == ".git":
                return parent.parent
        return directory
    return None


def project_key(cwd: Path) -> str:
    """Canonical project identity for `cwd`: the repo that owns it.

    Artifact subdirectories and linked worktrees both collapse onto the main
    checkout, so events raised from `<repo>/graphify-out` or
    `<repo>/.worktrees/<name>` group under `<repo>` instead of fragmenting
    into keys nothing joins back together. Outside a repo the cwd stands in
    for itself.

    Symlinks are resolved because only one of those two branches would do it
    otherwise: a worktree is found through the absolute gitdir git reports,
    while the parent walk keeps the path as given. On macOS that alone split
    one repo into `/var/...` and `/private/var/...`.
    """
    root = _main_repo_root(cwd)
    return str((root if root is not None else cwd).resolve())


def profile_name() -> str:
    """Configured profile whose config dir the agent runs under, or ''.

    Every profile records into a single metrics store, so a row that cannot
    name its profile cannot be told apart from another profile's after the
    fact. Degrades to '' on any failure — an unlabelled row beats a lost one.
    """
    try:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.core.config import load_config
        from lazy_harness.core.paths import config_file

        cfg = load_config(config_file())
        env_var = get_agent(cfg.agent.type).env_var()
        raw = os.environ.get(env_var, "") if env_var else ""
        if not raw:
            return ""
        target = Path(os.path.expanduser(raw)).resolve()
        for name, entry in cfg.profiles.items.items():
            entry_dir = getattr(entry, "config_dir", "") or ""
            if entry_dir and Path(os.path.expanduser(entry_dir)).resolve() == target:
                return name
    except Exception:
        return ""
    return ""


def resolve_memory_dir(
    payload: object, *, agent_dir: Path, sessions_subdir: str, cwd: Path
) -> Path:
    """Project dir that owns distilled memory, canonicalised across worktrees.

    Sessions belong to the checkout they ran in, but `decisions.jsonl` and
    `failures.jsonl` outlive any one worktree — writing them under a
    worktree's project dir strands them when the worktree is removed.
    """
    root = _main_repo_root(cwd)
    if root is None or root == cwd:
        return resolve_project_dir(
            payload, agent_dir=agent_dir, sessions_subdir=sessions_subdir, cwd=cwd
        )
    sessions_root = agent_dir / (sessions_subdir or "projects")
    return sessions_root / ("-" + str(root).replace("/", "-").lstrip("-"))


def memory_dir(
    payload: object,
    *,
    agent_dir: Path,
    sessions_subdir: str,
    cwd: Path,
    knowledge_root: Path | None,
) -> Path:
    """Where this project's distilled memory lives.

    Every hook used to compute a project dir and append `/ "memory"` itself.
    That put memory inside the agent's own project directory, which is named
    after the absolute path of the checkout — so the same repository on two
    machines wrote to two places, and the second one looked untouched.

    Resolves into the knowledge store when there is one, and otherwise keeps
    writing exactly where it always did. Unshared is a smaller problem than
    losing sight of memory already written.
    """
    from lazy_harness.core.memory_store import memory_dir_for

    legacy = resolve_memory_dir(
        payload, agent_dir=agent_dir, sessions_subdir=sessions_subdir, cwd=cwd
    )
    return memory_dir_for(cwd, knowledge_root=knowledge_root, legacy_project_dir=legacy)


def knowledge_root_for(cfg: object) -> Path | None:
    """The knowledge store root, or None when there is not a usable one.

    Fail-soft on purpose: a hook that cannot find the store falls back to the
    legacy location rather than failing the session.
    """
    try:
        from lazy_harness.knowledge.marker import resolve_root

        configured = getattr(getattr(cfg, "knowledge", None), "root", "") or None
        root = resolve_root(configured)
    except Exception:  # noqa: BLE001 — hooks degrade, they do not raise
        return None
    return root if root.is_dir() else None
