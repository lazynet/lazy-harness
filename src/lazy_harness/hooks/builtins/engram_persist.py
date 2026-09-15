"""Stop hook: mirror new JSONL entries into Engram via `engram save`.

Always abstains — a failure here must never block Claude Code's Stop chain.
All real work lives in lazy_harness.knowledge.engram_persist.EngramPersister.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from lazy_harness.agents.base import HookDecision, HookEvent


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


def main(event: HookEvent) -> HookDecision:
    """Persist this project's new memory entries and abstain.

    The decision is always empty: this hook has no output channel and no
    verdict to form. What it produces is on disk — a cursor, a metrics record
    and, when something went wrong, an error log — all under the runtime dir of
    the agent *this profile* runs.

    The single handler replaces two narrower ones. The `except ImportError`
    that used to wrap the imports was the last trace of this hook running as a
    bare script: `main` is reached only through `hooks.runner`, which imports
    the module from inside the package, so a package that cannot be imported
    never gets here at all.
    """
    try:
        from lazy_harness.core.config import Config, ConfigError, load_config
        from lazy_harness.core.paths import config_file
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
            knowledge_root=knowledge_root_for(cfg),
        )
        logs_dir = agent_dir / (subdirs.get("logs") or "logs")

        # A hook subprocess does not inherit the interactive shell's PATH, so an
        # explicitly configured path is the only reliable way to find the binary.
        configured_bin = cfg.memory.engram.binary if cfg is not None else ""

        # Keyed by the project's identity rather than its basename: two checkouts
        # named `proj` under different owners are different projects, and a cursor
        # they shared would skip whichever one ran second.
        cursor_dir = agent_dir / "engram-cursors"
        for part in identity_key(cwd).split("/"):
            if part and part not in (".", ".."):
                cursor_dir = cursor_dir / part

        EngramPersister(
            memory_dir=memory_dir,
            logs_dir=logs_dir,
            project_key=_resolve_project_key(cwd),
            engram_bin=configured_bin or None,
            cursor_dir=cursor_dir,
        ).persist_new_entries()
    except Exception:  # noqa: BLE001 — a Stop hook degrades, it does not raise
        return HookDecision()
    return HookDecision()
