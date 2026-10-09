"""Whether `graphify-out/graph.json` is fresh enough to trust.

graphify's incremental post-commit rebuild leaves the outputs untouched on a change
set with no code, so `graph.json` mtime falls behind HEAD while the graph is still
correct. Freshness is therefore measured against the last commit that touched a
file graphify indexes as code, not against HEAD.

Both the PreToolUse graph-assist hook and the SessionStart banner ask here, so
the rule has one definition.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

# Vendored from `graphify.detect.CODE_EXTENSIONS` at graphify 0.9.72. graphify's
# venv is not importable from `lh`; `lh doctor` reports drift against the installed one.
CODE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".F",
        ".F03",
        ".F08",
        ".F90",
        ".F95",
        ".asd",
        ".astro",
        ".bash",
        ".c",
        ".cbl",
        ".cc",
        ".cjs",
        ".cl",
        ".cls",
        ".cob",
        ".cobol",
        ".cpp",
        ".cpy",
        ".cs",
        ".cshtml",
        ".csproj",
        ".cts",
        ".cu",
        ".cuh",
        ".cxx",
        ".dart",
        ".dfm",
        ".dm",
        ".dme",
        ".dmf",
        ".dmi",
        ".dmm",
        ".dpk",
        ".dpr",
        ".ejs",
        ".erl",
        ".escript",
        ".ets",
        ".ex",
        ".exs",
        ".f",
        ".f03",
        ".f08",
        ".f90",
        ".f95",
        ".fsproj",
        ".go",
        ".gradle",
        ".groovy",
        ".h",
        ".hcl",
        ".hpp",
        ".hrl",
        ".inc",
        ".java",
        ".jl",
        ".js",
        ".json",
        ".jsx",
        ".kt",
        ".kts",
        ".lfm",
        ".lisp",
        ".lpk",
        ".lpr",
        ".lsp",
        ".lua",
        ".luau",
        ".m",
        ".metal",
        ".mjs",
        ".ml",
        ".mli",
        ".mm",
        ".mts",
        ".pas",
        ".php",
        ".pp",
        ".ps1",
        ".psd1",
        ".psm1",
        ".py",
        ".r",
        ".rake",
        ".razor",
        ".rb",
        ".resource",
        ".robot",
        ".rs",
        ".scala",
        ".sh",
        ".sln",
        ".slnx",
        ".sol",
        ".sql",
        ".sv",
        ".svelte",
        ".svh",
        ".swift",
        ".tf",
        ".tfvars",
        ".toc",
        ".trigger",
        ".ts",
        ".tsx",
        ".v",
        ".vb",
        ".vbproj",
        ".vue",
        ".xaml",
        ".zig",
    }
)

_GIT_TIMEOUT_S = 2
_CACHE_REL = Path("graphify-out") / "cache" / "lh-freshness.json"


def _git(root: Path, *args: str) -> str | None:
    """Stdout of a git call, "" when it succeeded with no output, None on any failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _pathspecs() -> list[str]:
    # icase: graphify lists both `.f90` and `.F90`; one case-insensitive glob covers both.
    return sorted({f":(glob,icase)**/*{ext.lower()}" for ext in CODE_EXTENSIONS})


def _read_cache(root: Path, head: str) -> tuple[bool, float | None]:
    """(hit, ts). A cache that is unreadable, malformed or for another HEAD is a miss."""
    try:
        data = json.loads((root / _CACHE_REL).read_text())
    except (OSError, ValueError):
        return False, None
    if not isinstance(data, dict) or data.get("head") != head:
        return False, None
    ts = data.get("ts")
    if ts is None:
        return True, None
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return False, None
    return True, float(ts)


def _write_cache(root: Path, head: str, ts: float | None) -> None:
    # Only inside an existing graphify-out/: this module never creates the directory.
    if not (root / "graphify-out").is_dir():
        return
    path = root / _CACHE_REL
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"head": head, "ts": ts}))
    except OSError:
        pass


def last_code_commit_ts(root: Path) -> float | None:
    """Committer time of the last commit on HEAD touching a code file.

    None when there is no such commit, or git failed — callers that must tell
    those apart use `is_fresh`.
    """
    return _resolve(root)[1]


def _resolve(root: Path) -> tuple[bool, float | None]:
    """(known, ts): known is False when git could not answer."""
    head = _git(root, "rev-parse", "HEAD")
    if not head:
        return False, None
    hit, ts = _read_cache(root, head)
    if hit:
        return True, ts
    out = _git(root, "log", "-1", "--format=%ct", "--", *_pathspecs())
    if out is None:
        return False, None
    try:
        ts = float(out) if out else None
    except ValueError:
        return False, None
    _write_cache(root, head, ts)
    return True, ts


def is_fresh(root: Path) -> bool | None:
    """True/False for the graph of the checkout at `root`; None when git cannot say."""
    graph = root / "graphify-out" / "graph.json"
    try:
        mtime = graph.stat().st_mtime
    except OSError:
        return False
    known, ts = _resolve(root)
    if not known:
        return None
    return ts is None or mtime >= ts
