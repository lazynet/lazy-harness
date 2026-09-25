"""Read-only inventory of statically discovered instruction bytes."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from lazy_harness.agents.registry import agent_for_profile
from lazy_harness.core.config import Config
from lazy_harness.core.paths import expand_path
from lazy_harness.core.repo_instructions import APPENDIX_NAME, CANONICAL_NAME
from lazy_harness.deploy.engine import UnknownProfileError


def inspect_context_budget(
    cfg: Config, profile: str, cwd: Path, limits: tuple[int, int]
) -> dict[str, object]:
    """Count known static files selected by the configured agent at cwd."""
    entry = cfg.profiles.items.get(profile)
    if entry is None:
        raise UnknownProfileError(profile, cfg.profiles.items)
    agent = agent_for_profile(cfg, profile)
    cwd = cwd.resolve()
    profile_dir = expand_path(entry.config_dir)
    sources: list[dict[str, object]] = []
    missing: list[str] = []
    shadowed: list[str] = []
    alternatives: list[str] = []
    aliases: list[str] = []
    truncated: list[str] = []
    unreadable: list[str] = []
    project_max_bytes = 32768
    fallbacks: list[str] = []
    if agent.name == "codex":
        try:
            settings = tomllib.loads((profile_dir / "config.toml").read_text())
            configured_names = settings.get("project_doc_fallback_filenames", [])
            configured_limit = settings.get("project_doc_max_bytes", 32768)
            if isinstance(configured_names, list) and all(
                isinstance(x, str) for x in configured_names
            ):
                fallbacks = configured_names
            if (
                isinstance(configured_limit, int)
                and not isinstance(configured_limit, bool)
                and configured_limit >= 0
            ):
                project_max_bytes = configured_limit
        except FileNotFoundError:
            pass
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            unreadable.append(str(profile_dir / "config.toml"))

    def read(path: Path, *, required: bool = False) -> bytes | None:
        try:
            return path.read_bytes()
        except FileNotFoundError:
            if required:
                missing.append(str(path))
        except (OSError, PermissionError):
            unreadable.append(str(path))
        return None

    def add(path: Path, kind: str, raw: bytes) -> None:
        if path.is_symlink():
            aliases.append(str(path))
        sources.append(
            {"kind": kind, "path": str(path), "bytes": len(raw), "lines": len(raw.splitlines())}
        )

    if agent.name == "codex":
        global_candidates = [profile_dir / "AGENTS.override.md", profile_dir / CANONICAL_NAME]
        for candidate in global_candidates:
            raw = read(candidate, required=candidate == global_candidates[-1])
            if raw:
                add(candidate, "global", raw)
                shadowed.extend(
                    str(path) for path in global_candidates if path != candidate and path.is_file()
                )
                break
    else:
        for doc in agent.system_docs():
            path = profile_dir / doc
            raw = read(path, required=True)
            if raw is not None:
                add(path, "global", raw)

    chain = list(reversed((cwd, *cwd.parents)))
    if agent.name == "codex":
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            root = Path(result.stdout.strip())
            relative_parts = cwd.relative_to(root).parts
            chain = [
                root,
                *(
                    root / Path(*relative_parts[:index])
                    for index in range(1, len(relative_parts) + 1)
                ),
            ]
        else:
            chain = [cwd]
    agents = [
        directory / CANONICAL_NAME for directory in chain if (directory / CANONICAL_NAME).is_file()
    ]
    claudes = [
        directory / APPENDIX_NAME for directory in chain if (directory / APPENDIX_NAME).is_file()
    ]
    if agent.name == "codex":
        chosen = []
        used = 0
        cap_reached = False
        for directory in chain:
            candidates = [directory / "AGENTS.override.md", directory / CANONICAL_NAME]
            candidates.extend(directory / name for name in fallbacks)
            selected = None
            selected_raw = None
            for path in candidates:
                raw = read(path)
                if raw is not None:
                    selected = path
                    selected_raw = raw
                    break
            if selected is None or selected_raw is None:
                continue
            shadowed.extend(str(path) for path in candidates if path != selected and path.is_file())
            if cap_reached or used >= project_max_bytes and selected_raw:
                truncated.append(str(selected))
                continue
            if used + len(selected_raw) > project_max_bytes:
                truncated.append(str(selected))
                cap_reached = True
            used += min(len(selected_raw), project_max_bytes - used)
            chosen.append(selected)
            add(selected, "repository", selected_raw)
        alternatives = [str(path) for path in claudes]
    elif agent.name == "claude-code":
        chosen = claudes if claudes else agents
        shadowed = [str(path) for path in agents] if claudes else []
    else:
        chosen = []
        alternatives = [str(path) for path in (*agents, *claudes)]
    if agent.name != "codex":
        for path in chosen:
            raw = read(path)
            if raw is not None:
                add(path, "repository", raw)
    if (
        not chosen
        and agent.name in {"codex", "claude-code"}
        and not truncated
        and not any(Path(path).parent in chain for path in unreadable)
    ):
        missing.append(str(cwd / CANONICAL_NAME))

    total_bytes = sum(int(row["bytes"]) for row in sources)
    total_lines = sum(int(row["lines"]) for row in sources)
    max_lines, max_bytes = limits
    unknown = ["dynamic hook output", "skills", "tools"]
    if agent.name == "claude-code":
        unknown.extend(["CLAUDE.md imports", ".claude/rules", "local and managed instructions"])
    if agent.name == "codex":
        unknown.append("Codex CLI and layered config overrides")
    if aliases:
        unknown.append("symlink alias injection multiplicity")
    if agent.name not in {"codex", "claude-code"}:
        unknown.append("repository instruction discovery")
    return {
        "profile": profile,
        "agent": agent.name,
        "cwd": str(cwd),
        "sources": sources,
        "total_bytes": total_bytes,
        "total_lines": total_lines,
        "total_status": (
            "upper_bound_selected_readable_files" if truncated else "selected_readable_file_bytes"
        ),
        "limits": {"lines": max_lines, "bytes": max_bytes},
        "over_limit": any(
            int(row["lines"]) > max_lines or int(row["bytes"]) > max_bytes for row in sources
        ),
        "missing": missing,
        "shadowed": shadowed,
        "alternatives": alternatives,
        "aliases": aliases,
        "truncated": truncated,
        "unreadable": unreadable,
        "project_doc_max_bytes": project_max_bytes if agent.name == "codex" else None,
        "unknown": unknown,
    }
