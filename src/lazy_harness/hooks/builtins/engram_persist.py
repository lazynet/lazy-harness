"""Stop hook: mirror new JSONL entries into Engram via `engram save`.

Always abstains — a failure here must never block Claude Code's Stop chain.
All real work lives in lazy_harness.knowledge.engram_persist.EngramPersister.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from lazy_harness.agents.base import HookDecision, HookEvent

if TYPE_CHECKING:
    from lazy_harness.core.config import Config


def _resolve_project_key(cwd: Path) -> str:
    """Return canonical Engram project key.

    Uses `git rev-parse --git-common-dir` so worktrees resolve to the
    main repo basename (preventing fragmentation between e.g. `lazy-harness`
    and `.worktrees/feat-foo`). Falls back to cwd basename if not in a
    git repo or if git is not on PATH.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            common_git = Path(proc.stdout.strip())
            repo_root = common_git.parent
            if repo_root.name:
                return repo_root.name
    except OSError:
        pass
    return cwd.name


def _profile_cursor_dirs(
    cfg: Config | None, own_agent_dir: Path, cursor_for: Callable[[Path], Path]
) -> list[Path]:
    """Every profile's pre-shared cursor for this project, this one's included."""
    from lazy_harness.hooks.builtins._shared import agent_dir_for

    dirs = [cursor_for(own_agent_dir)]
    if cfg is None:
        return dirs
    for name in cfg.profiles.items:
        try:
            candidate = cursor_for(agent_dir_for(cfg, name)[1])
        except Exception:  # noqa: BLE001 — one bad profile must not block the rest
            continue
        if candidate not in dirs:
            dirs.append(candidate)
    return dirs


def main(event: HookEvent) -> HookDecision:
    """Persist this project's new memory entries and abstain.

    The decision is always empty: this hook has no output channel and no
    verdict to form. What it produces is on disk — a metrics record and, when
    something went wrong, an error log under the runtime dir of the agent *this
    profile* runs, and a cursor that is per machine when memory lives in the
    knowledge store and per profile otherwise.

    The single handler replaces two narrower ones. The `except ImportError`
    that used to wrap the imports was the last trace of this hook running as a
    bare script: `main` is reached only through `hooks.runner`, which imports
    the module from inside the package, so a package that cannot be imported
    never gets here at all.
    """
    try:
        from lazy_harness.core.config import ConfigError, load_config
        from lazy_harness.core.paths import config_file, data_dir
        from lazy_harness.core.project_identity import project_key as identity_key
        from lazy_harness.hooks.builtins._shared import agent_dir_for, knowledge_root_for
        from lazy_harness.hooks.builtins._shared import memory_dir as shared_memory_dir
        from lazy_harness.knowledge.engram_persist import EngramPersister

        cf = config_file()
        cfg: Config | None = None
        if cf.is_file():
            try:
                cfg = load_config(cf)
            except ConfigError:
                cfg = None

        # Config first, then the directories: every path below is keyed by the
        # agent this profile runs, and writing before that resolves is what sent
        # `context-inject`'s log to the global agent's directory (PR #300).
        agent, agent_dir = agent_dir_for(cfg, event.profile)

        # `parse_hook_input` yields `Path("")` — which is `Path(".")`, and
        # truthy — for a payload that names no cwd, so the `or Path.cwd()` this
        # hook used to rely on would no longer fire. Without the guard the
        # project key becomes the empty basename and the encoded project dir
        # `-.`, pointing every checkout at one shared directory.
        cwd = event.cwd if event.cwd != Path(".") else Path.cwd()

        knowledge_root = knowledge_root_for(cfg)
        subdirs = agent.session_dirs()
        # The *declared* transcript, not `existing_transcript` of it:
        # `resolve_project_dir` stats only its parent, so filtering a transcript
        # the agent has named but not yet written would silently fall back to
        # encoding the cwd and read memory from a directory nothing wrote to.
        memory_dir = shared_memory_dir(
            event.transcript_path,
            agent_dir=agent_dir,
            sessions_subdir=subdirs.get("sessions") or "projects",
            cwd=cwd,
            knowledge_root=knowledge_root,
        )
        logs_dir = agent_dir / (subdirs.get("logs") or "logs")

        # A hook subprocess does not inherit the interactive shell's PATH, so an
        # explicitly configured path is the only reliable way to find the binary.
        configured_bin = cfg.memory.engram.binary if cfg is not None else ""

        # Keyed by the project's identity rather than its basename: two checkouts
        # named `proj` under different owners are different projects, and a cursor
        # they shared would skip whichever one ran second.
        key_parts = [p for p in identity_key(cwd).split("/") if p and p not in (".", "..")]

        def profile_cursor_dir(directory: Path) -> Path:
            return directory.joinpath("engram-cursors", *key_parts)

        cursor_dir = profile_cursor_dir(agent_dir)
        adopt: tuple[Path, ...] = ()
        # Memory in the store is one file every profile appends to and mirrors
        # into one machine-wide database, so its cursor is one per machine too —
        # keyed by the memory's own path, outside the store because the store
        # travels between machines and the database does not. Memory outside
        # the store is per profile, and so is its cursor.
        if knowledge_root is not None and memory_dir.is_relative_to(knowledge_root):
            cursor_dir = data_dir().joinpath(
                "engram-cursors", *memory_dir.relative_to(knowledge_root).parts
            )
            adopt = tuple(_profile_cursor_dirs(cfg, agent_dir, profile_cursor_dir))

        EngramPersister(
            memory_dir=memory_dir,
            logs_dir=logs_dir,
            project_key=_resolve_project_key(cwd),
            engram_bin=configured_bin or None,
            cursor_dir=cursor_dir,
            adopt_cursor_dirs=adopt,
        ).persist_new_entries()
    except Exception:  # noqa: BLE001 — a Stop hook degrades, it does not raise
        return HookDecision()
    return HookDecision()
