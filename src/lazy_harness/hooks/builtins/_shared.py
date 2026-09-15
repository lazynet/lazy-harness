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
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from lazy_harness.agents.base import AgentAdapter, TranscriptReader
    from lazy_harness.core.config import Config


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
    """Transcript path as declared in a raw stdin payload, without stat'ing it.

    The payload-reading half, kept for the builtins that have not moved onto
    `HookEvent` yet. A migrated hook has `event.transcript_path` instead and
    never calls this.
    """
    if not isinstance(payload, Mapping):
        return None
    for key in ("transcript_path", "transcriptPath", "input"):
        raw = payload.get(key)
        if isinstance(raw, str) and raw:
            return Path(raw)
    return None


def existing_transcript(declared: Path | None) -> Path | None:
    """The declared transcript if it is on disk, else None.

    `HookEvent.transcript_path` is what the payload named, not what exists:
    at `SessionStart` the file is routinely not written yet. The pre-runner
    helper this replaces stat'd it as part of reading the payload, so without
    this the check disappears silently at every call site at once.
    """
    return declared if declared is not None and declared.is_file() else None


def _project_dir_of(transcript: Path | None) -> Path | None:
    """Agent-owned per-project session dir the transcript sits in.

    The agent encodes the cwd into this directory name with a scheme that has
    changed across releases, so it is read here rather than recomputed. Only
    the parent is required to exist: at SessionStart the transcript is not
    written yet, which is why this takes the declared path rather than
    `existing_transcript` of it.
    """
    if transcript is None:
        return None
    parent = transcript.parent
    return parent if parent.is_dir() else None


def resolve_project_dir(
    transcript: Path | None, *, agent_dir: Path, sessions_subdir: str, cwd: Path
) -> Path:
    """Per-project session dir: the agent's own, else one derived from `cwd`.

    Only a declared dir inside the adapter's sessions root is honoured, so
    harness artifacts never escape it (ADR-032). The cwd-derived fallback
    matches agents whose encoding is a plain slash-to-dash rewrite.
    """
    sessions_root = agent_dir / (sessions_subdir or "projects")
    declared = _project_dir_of(transcript)
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
    transcript: Path | None, *, agent_dir: Path, sessions_subdir: str, cwd: Path
) -> Path:
    """Project dir that owns distilled memory, canonicalised across worktrees.

    Sessions belong to the checkout they ran in, but `decisions.jsonl` and
    `failures.jsonl` outlive any one worktree — writing them under a
    worktree's project dir strands them when the worktree is removed.
    """
    root = _main_repo_root(cwd)
    if root is None or root == cwd:
        return resolve_project_dir(
            transcript, agent_dir=agent_dir, sessions_subdir=sessions_subdir, cwd=cwd
        )
    sessions_root = agent_dir / (sessions_subdir or "projects")
    return sessions_root / ("-" + str(root).replace("/", "-").lstrip("-"))


def memory_dir(
    transcript: Path | None,
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
        transcript, agent_dir=agent_dir, sessions_subdir=sessions_subdir, cwd=cwd
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


def agent_dir_for(cfg: Config | None, profile: str) -> tuple[AgentAdapter, Path]:
    """The agent one profile runs and the runtime dir its hooks write under.

    One importable answer to a question six builtins used to answer twice each,
    both times globally: `get_agent(cfg.agent.type)` for the adapter and
    `agent_runtime_dir(agent)` for the directory. Neither read the profile the
    hook was invoked with, so on a machine whose profiles run different agents a
    hook wrote its log, its cursor and its session export under whichever agent
    the global key happened to name.

    The step 4 contract gate measured the far end of that: `context-inject`,
    running under `--profile gate-throwaway`, wrote into the user's real
    `~/.codex` — `CODEX_HOME` is absent from a hook subprocess, the adapter
    declares no global link on purpose, and the last resort is `~/.<agent name>`.
    Passing the profile's own `config_dir` is what stops that fall-through.

    No config is the same degradation `transcript_reader` applies: a machine that
    has not run `lh init` still has an agent whose directories its hooks use.
    """
    from lazy_harness.agents.registry import agent_for_profile, get_agent
    from lazy_harness.core.paths import agent_runtime_dir

    if cfg is None:
        agent = get_agent("claude-code")
        return agent, agent_runtime_dir(agent)
    entry = cfg.profiles.items.get(profile)
    agent = agent_for_profile(cfg, profile)
    return agent, agent_runtime_dir(agent, profile_config_dir=entry.config_dir if entry else None)


def transcript_reader(profile: str, cfg: Config | None = None) -> TranscriptReader | None:
    """The `TranscriptReader` for the agent this profile runs, or None.

    One importable answer to "can this session's transcript be read, and by
    what". Decision 11 of
    `specs/designs/2026-09-13-multi-agent-harness-design.md` makes transcript
    dependence a declared capability, and a hook that needs a signal has to be
    able to learn that the signal is *absent* — `None` is that answer. A reader
    that yielded nothing instead would be indistinguishable from a session that
    genuinely carries no goal, which is the silent pass the decision exists to
    prevent.

    Resolved per profile rather than globally, because `[profiles.<name>].agent`
    is what decides whose wire format a session speaks.

    An unreadable config degrades to the defaults rather than to `None`: the
    runner resolves an absent config the same way and for the same reason — a
    machine that has not run `lh init` still has an agent whose transcript its
    hooks can read.

    `cfg` is an optional override for a caller that has already loaded one.
    Hooks pass nothing and get the load above; `lh doctor` passes its own so
    that one command does not answer the same question from two reads of the
    same file.

    The Protocol is imported under `TYPE_CHECKING` so that this module keeps
    every runtime import inside a function — a hook's import cost is paid on
    every tool call.
    """
    try:
        from lazy_harness.agents.base import TranscriptReader
        from lazy_harness.agents.registry import agent_for_profile
        from lazy_harness.core.config import Config, ConfigError, load_config
        from lazy_harness.core.paths import config_file

        if cfg is None:
            try:
                cfg = load_config(config_file())
            except (ConfigError, OSError):
                cfg = Config()
        adapter = agent_for_profile(cfg, profile)
    except Exception:  # noqa: BLE001 — hooks degrade, they do not raise
        return None
    return adapter if isinstance(adapter, TranscriptReader) else None
