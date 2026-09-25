"""Graph assist: answer code-symbol searches from graphify's graph.

Design: `specs/designs/2026-09-24-graph-assist-design.md`. The hook
`pre-tool-use-graph-assist` is the consumer; this module owns the index built
from `graphify-out/graph.json` and how an entry is rendered.

An index rather than `graphify explain`: `explain` measured 1.09–1.13 s on this
repository, half of it process start-up, and a prebuilt lookup costs
milliseconds. The price is a dependency on the `graph.json` schema, pinned by a
test against a real 0.9.67 file.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import time
from collections.abc import Callable
from pathlib import Path

from lazy_harness.core.config import atomic_write_text

INDEX_NAME = "lh-graph-assist.json"
INDEX_VERSION = 1
MAX_DEFS = 3
MAX_NEIGHBOURS = 5
MAX_CHARS = 2400  # ~600 tokens at 4 chars per token
BUILD_DEADLINE_S = 1.5

_CALL_RELATIONS = frozenset({"calls", "indirect_call"})
_DOC_RELATIONS = frozenset({"references", "uses"})

Entries = dict[str, list[dict]]


def normalise(label: str) -> str:
    """Index key: lowercased, without a trailing `()` or a method's leading `.`."""
    return label.strip().lower().removesuffix("()").lstrip(".")


def _is_document(node: dict) -> bool:
    return node.get("file_type") == "document" or str(node.get("source_file", "")).endswith(".md")


def _is_definition(node: dict) -> bool:
    """A code symbol with a location, excluding file nodes and external imports."""
    if node.get("file_type") != "code":
        return False
    source_file = node.get("source_file")
    label = node.get("label")
    if not isinstance(source_file, str) or not source_file:
        return False
    if not isinstance(label, str) or not label:
        return False
    if not node.get("source_location"):
        return False
    return label != source_file.rsplit("/", 1)[-1]


def _unique(items: list[str]) -> list[str]:
    return sorted(set(items))


def build_index(graph: dict) -> Entries:
    """Key every definition in `graph` by its normalised label."""
    raw_nodes = graph.get("nodes")
    raw_links = graph.get("links")
    nodes = {
        n["id"]: n
        for n in (raw_nodes if isinstance(raw_nodes, list) else [])
        if isinstance(n, dict) and isinstance(n.get("id"), str)
    }
    links = [
        lk for lk in (raw_links if isinstance(raw_links, list) else []) if isinstance(lk, dict)
    ]

    calls_in: dict[str, list[str]] = {}
    calls_out: dict[str, list[str]] = {}
    docs: dict[str, list[str]] = {}
    for link in links:
        relation = link.get("relation")
        source = nodes.get(link.get("source"))  # type: ignore[arg-type]
        target = nodes.get(link.get("target"))  # type: ignore[arg-type]
        if source is None or target is None:
            continue
        if relation in _CALL_RELATIONS:
            calls_out.setdefault(source["id"], []).append(str(target.get("label", "")))
            calls_in.setdefault(target["id"], []).append(str(source.get("label", "")))
        elif relation in _DOC_RELATIONS:
            for this, other in ((source, target), (target, source)):
                if _is_document(other) and not _is_document(this):
                    docs.setdefault(this["id"], []).append(str(other.get("source_file", "")))

    entries: Entries = {}
    for nid, node in nodes.items():
        if not _is_definition(node):
            continue
        entries.setdefault(normalise(node["label"]), []).append(
            {
                "label": node["label"],
                "source_file": node["source_file"],
                "source_location": str(node["source_location"]),
                "calls_in": _unique(calls_in.get(nid, [])),
                "calls_out": _unique(calls_out.get(nid, [])),
                "docs": _unique([d for d in docs.get(nid, []) if d]),
            }
        )
    return entries


def graph_path(repo_root: Path) -> Path:
    return repo_root / "graphify-out" / "graph.json"


def index_path(repo_root: Path) -> Path:
    return repo_root / "graphify-out" / "cache" / INDEX_NAME


def _read_graph(repo_root: Path) -> tuple[dict, float] | None:
    graph_json = graph_path(repo_root)
    try:
        mtime = graph_json.stat().st_mtime
        data = json.loads(graph_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return (data, mtime) if isinstance(data, dict) else None


def _persist(repo_root: Path, entries: Entries, graph_mtime: float) -> Path:
    path = index_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": INDEX_VERSION, "graph_mtime": graph_mtime, "entries": entries}
    atomic_write_text(path, json.dumps(payload, separators=(",", ":")))
    # The index's own mtime is what freshness compares against the graph's, so
    # it is pinned to the graph it was built from rather than to "now".
    os.utime(path, (graph_mtime, graph_mtime))
    return path


def write_index(repo_root: Path) -> Path | None:
    """Build and persist the index for `repo_root`. None if the graph is unreadable."""
    read = _read_graph(repo_root)
    if read is None:
        return None
    graph, mtime = read
    return _persist(repo_root, build_index(graph), mtime)


def _read_index(repo_root: Path, graph_mtime: float) -> Entries | None:
    try:
        payload = json.loads(index_path(repo_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != INDEX_VERSION:
        return None
    built_from = payload.get("graph_mtime")
    entries = payload.get("entries")
    if not isinstance(built_from, int | float) or built_from < graph_mtime:
        return None
    return entries if isinstance(entries, dict) else None


def load_index(
    repo_root: Path,
    *,
    deadline_s: float = BUILD_DEADLINE_S,
    clock: Callable[[], float] = time.monotonic,
) -> Entries | None:
    """The fresh index for `repo_root`, building it when missing or stale.

    A build that passes `deadline_s` is abandoned and nothing is persisted, so
    the caller answers nothing this time rather than hold up a tool call. The
    deadline is checked between the parse and the persist, the two phases that
    scale with the graph.
    """
    try:
        graph_mtime = graph_path(repo_root).stat().st_mtime
    except OSError:
        return None
    cached = _read_index(repo_root, graph_mtime)
    if cached is not None:
        return cached

    start = clock()
    read = _read_graph(repo_root)
    if read is None:
        return None
    graph, mtime = read
    entries = build_index(graph)
    if clock() - start > deadline_s:
        return None
    try:
        _persist(repo_root, entries, mtime)
    except OSError:
        pass
    return entries


def lookup(entries: Entries, pattern: str) -> tuple[str, list[dict]] | None:
    """Definitions for `pattern`: exact key first, then a qualified suffix.

    `mod.func` and `Class.method` resolve to the definitions of `func`/`method`
    whose file stem or label path carries the qualifier. Every match is
    returned — homonyms are listed, never picked between silently.
    """
    key = normalise(pattern)
    defs = entries.get(key)
    if defs:
        return defs[0]["label"], defs
    if "." not in key:
        return None
    qualifier, _, name = key.rpartition(".")
    last = qualifier.rsplit(".", 1)[-1]
    candidates = entries.get(name, [])
    matched = [d for d in candidates if _qualified_by(d, last, entries)]
    if not matched:
        return None
    return matched[0]["label"], matched


def _qualified_by(definition: dict, qualifier: str, entries: Entries) -> bool:
    source_file = str(definition.get("source_file", ""))
    stem = source_file.rsplit("/", 1)[-1].removesuffix(".py").lower()
    if stem == qualifier:
        return True
    # `Class.method`: the class is a definition in the same file.
    return any(d.get("source_file") == source_file for d in entries.get(qualifier, []))


def _location(definition: dict) -> str:
    line = str(definition.get("source_location", "")).removeprefix("L")
    return f"{definition.get('source_file', '')}:{line}" if line else str(definition["source_file"])


def _neighbours(label: str, items: list[str]) -> str:
    shown = ", ".join(items[:MAX_NEIGHBOURS])
    extra = len(items) - MAX_NEIGHBOURS
    return f"  {label}: {shown}" + (f" … (+{extra})" if extra > 0 else "")


def render(label: str, defs: list[dict], *, max_defs: int = MAX_DEFS) -> str:
    """Markdown for the agent: information about the symbol, never an order."""
    count = len(defs)
    noun = "definition" if count == 1 else "definitions"
    lines = [f"Graph: {label} — {count} {noun}"]
    for definition in defs[:max_defs]:
        lines.append(f"- {_location(definition)}")
        for title, key in (("called by", "calls_in"), ("calls", "calls_out"), ("named in", "docs")):
            items = definition.get(key) or []
            if items:
                lines.append(_neighbours(title, items))
    if count > max_defs:
        lines.append(f"(+{count - max_defs} more)")
    text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 1].rsplit("\n", 1)[0] + "\n…"
    return text


# --- search classification (spec §3.1, filter rules 3 and 4) ---

SEARCH_TOOLS = frozenset({"grep", "rg", "ugrep", "egrep"})

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*\(?\)?$")
_DECL_PREFIX = re.compile(r"^(?:def|class|function)\s+")

# Options that consume the next argument. A value mistaken for the pattern would
# be a wrong hit, which is worse than silence, so each tool's set is its own:
# `-r` is recursion to grep and a replacement string to rg.
_GREP_VALUE_FLAGS = frozenset(
    {
        "-e", "-f", "-m", "-A", "-B", "-C", "-d", "-D",
        "--regexp", "--file", "--max-count", "--context", "--after-context",
        "--before-context", "--include", "--exclude", "--exclude-dir",
    }
)  # fmt: skip
_RG_VALUE_FLAGS = frozenset(
    {
        "-e", "-f", "-t", "-T", "-g", "-m", "-A", "-B", "-C", "-r", "-E", "-j", "-M",
        "--regexp", "--file", "--type", "--type-not", "--glob", "--iglob", "--max-count",
        "--context", "--after-context", "--before-context", "--replace", "--encoding",
        "--threads", "--max-columns",
    }
)  # fmt: skip
_PATTERN_FLAGS = frozenset({"-e", "--regexp"})
_SEPARATORS = frozenset({";", "&&", "||", "&", "|"})


def identifier(pattern: str) -> str | None:
    """The identifier `pattern` names, or None for a regex, glob or phrase."""
    text = pattern.strip().strip("'\"").strip()
    text = _DECL_PREFIX.sub("", text)
    return text if IDENTIFIER_RE.match(text) else None


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _segments(command: str) -> list[tuple[list[str], bool]] | None:
    """Split a shell command into (argv, fed_by_pipe) segments; None if unparsable."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[tuple[list[str], bool]] = []
    current: list[str] = []
    piped = False
    for token in tokens:
        if token in _SEPARATORS:
            segments.append((current, piped))
            current, piped = [], token == "|"
        else:
            current.append(token)
    segments.append((current, piped))
    return segments


def _parse_search(argv: list[str]) -> tuple[str, list[str]] | None:
    """(pattern, paths) from a grep-family argv, or None."""
    tool = argv[0].rsplit("/", 1)[-1]
    value_flags = _RG_VALUE_FLAGS if tool == "rg" else _GREP_VALUE_FLAGS
    pattern: str | None = None
    positionals: list[str] = []
    args = iter(argv[1:])
    options_done = False
    for arg in args:
        if not options_done and arg == "--":
            options_done = True
        elif not options_done and arg.startswith("-") and arg != "-":
            if arg in value_flags:
                value = next(args, None)
                if value is None:
                    return None
                if arg in _PATTERN_FLAGS and pattern is None:
                    pattern = value
        else:
            positionals.append(arg)
    if pattern is None:
        if not positionals:
            return None
        pattern, positionals = positionals[0], positionals[1:]
    return pattern, positionals


def _bash_target(command: str, repo_root: Path, cwd: Path) -> str | None:
    segments = _segments(command)
    if segments is None:
        return None
    here = cwd
    for argv, piped in segments:
        if not argv:
            continue
        name = argv[0].rsplit("/", 1)[-1]
        if name == "cd" and len(argv) == 2:
            here = (here / argv[1]) if not argv[1].startswith("/") else Path(argv[1])
            continue
        if name not in SEARCH_TOOLS:
            continue
        if piped:
            return None
        parsed = _parse_search(argv)
        if parsed is None:
            return None
        pattern, paths = parsed
        targets = [here / p for p in paths] if paths else [here]
        if not all(_inside(t, repo_root) for t in targets):
            return None
        return identifier(pattern)
    return None


def search_target(tool_name: str, tool_input: object, repo_root: Path, cwd: Path) -> str | None:
    """The identifier a `Grep`/`Bash` call searches the repository for, or None."""
    if not isinstance(tool_input, dict):
        return None
    if tool_name == "Grep":
        pattern = tool_input.get("pattern")
        path = tool_input.get("path")
        if not isinstance(pattern, str):
            return None
        if path is not None:
            if not isinstance(path, str):
                return None
            if not _inside(cwd / path, repo_root):
                return None
        return identifier(pattern)
    if tool_name == "Bash":
        command = tool_input.get("command")
        return _bash_target(command, repo_root, cwd) if isinstance(command, str) else None
    return None


def is_search_call(tool_name: str, tool_input: object) -> bool:
    """Whether a call runs a search tool at all, before any repository check.

    The cheap gate in front of the git subprocesses: most shell calls are not
    searches, and they are neither evaluated nor counted.
    """
    if tool_name == "Grep":
        return True
    if tool_name != "Bash" or not isinstance(tool_input, dict):
        return False
    command = tool_input.get("command")
    if not isinstance(command, str):
        return False
    segments = _segments(command)
    if segments is None:
        return False
    return any(argv and argv[0].rsplit("/", 1)[-1] in SEARCH_TOOLS for argv, _ in segments)
