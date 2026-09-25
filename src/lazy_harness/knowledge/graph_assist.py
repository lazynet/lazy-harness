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
    # Any change, not only a newer graph: a copy that keeps an older mtime is
    # still a different graph.
    if not isinstance(built_from, int | float) or built_from != graph_mtime:
        return None
    return entries if isinstance(entries, dict) else None


def load_index(
    repo_root: Path,
    *,
    deadline_s: float = BUILD_DEADLINE_S,
    clock: Callable[[], float] = time.monotonic,
) -> Entries | None:
    """The fresh index for `repo_root`, building it when missing or stale.

    A build that passes `deadline_s` answers nothing for this call, which has
    already waited for it, but is persisted, so the cost is paid once rather
    than on every search until something else writes the index. The deadline
    cannot interrupt the parse; measured on this repository's 15 000-node graph
    the whole build takes about 0.1 s.
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
    try:
        _persist(repo_root, entries, mtime)
    except OSError:
        pass
    return None if clock() - start > deadline_s else entries


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

# Option vocabulary per tool. A value mistaken for the pattern is a wrong hit,
# which is worse than silence, so anything the tables do not cover resolves to
# None: an unknown long option has unknown arity, and guessing it is how
# `rg --sort path foo` once reported `path`. Each tool keeps its own tables
# because `-r` is recursion to grep and a replacement string to rg.
_GREP_VALUE_SHORT = frozenset("efmABCdD")
_RG_VALUE_SHORT = frozenset("eftTgmABCrEjM")
_GREP_VALUE_LONG = frozenset(
    {
        "--regexp", "--file", "--max-count", "--context", "--after-context",
        "--before-context", "--include", "--exclude", "--exclude-dir", "--devices",
        "--directories", "--label", "--binary-files",
    }
)  # fmt: skip
_RG_VALUE_LONG = frozenset(
    {
        "--regexp", "--file", "--type", "--type-not", "--glob", "--iglob", "--max-count",
        "--context", "--after-context", "--before-context", "--replace", "--encoding",
        "--threads", "--max-columns", "--sort", "--sortr", "--color", "--colors",
        "--max-depth", "--type-add", "--type-clear", "--pre", "--pre-glob",
        "--ignore-file", "--path-separator", "--context-separator", "--engine",
        "--max-filesize", "--dfa-size-limit", "--regex-size-limit",
    }
)  # fmt: skip
_FLAG_LONG = frozenset(
    {
        "--recursive", "--dereference-recursive", "--line-number", "--no-line-number",
        "--ignore-case", "--no-ignore-case", "--smart-case", "--case-sensitive",
        "--count", "--count-matches", "--files-with-matches", "--files-without-match",
        "--word-regexp", "--line-regexp", "--fixed-strings", "--extended-regexp",
        "--perl-regexp", "--basic-regexp", "--invert-match", "--only-matching",
        "--quiet", "--silent", "--no-messages", "--with-filename", "--no-filename",
        "--null", "--text", "--byte-offset", "--initial-tab", "--hidden", "--no-ignore",
        "--no-ignore-vcs", "--follow", "--json", "--vimgrep", "--heading",
        "--no-heading", "--multiline", "--pcre2", "--trim", "--stats", "--unrestricted",
        "--no-config", "--column", "--search-zip", "--line-buffered", "--block-buffered",
        "--null-data", "--binary", "--crlf", "--passthru", "--pretty", "--include-zero",
        "--sort-files", "--one-file-system", "--no-require-git", "--no-ignore-dot",
        "--no-ignore-parent", "--no-ignore-global", "--no-ignore-exclude",
        "--glob-case-insensitive", "--max-columns-preview",
        # grep's `--color[=WHEN]` takes its value only after `=`; rg's `--color`
        # always takes one and is in `_RG_VALUE_LONG`, which is checked first.
        "--color", "--colour",
    }
)  # fmt: skip
# Options after which the positionals are not a pattern at all.
_NO_PATTERN = frozenset({"--file", "--files", "--type-list"})
_SEPARATORS = frozenset({";", "&&", "||", "&", "|"})
_PUNCTUATION = frozenset("();&|{}")
_GROUPING = frozenset("(){}")


def identifier(pattern: str) -> str | None:
    """The identifier `pattern` names, or None for a regex, glob or phrase."""
    text = pattern.strip().strip("'\"").strip()
    text = _DECL_PREFIX.sub("", text)
    return text if IDENTIFIER_RE.match(text) else None


def is_inside(path: Path, root: Path) -> bool:
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


def _unresolvable(token: str) -> bool:
    """A path the shell would expand, which cannot be placed statically."""
    return token.startswith("~") or "$" in token or "`" in token


def _parse_search(argv: list[str]) -> tuple[str, list[str]] | None:
    """(pattern, paths) from a grep-family argv, or None when unsure."""
    rg = argv[0].rsplit("/", 1)[-1] == "rg"
    value_short = _RG_VALUE_SHORT if rg else _GREP_VALUE_SHORT
    value_long = _RG_VALUE_LONG if rg else _GREP_VALUE_LONG
    pattern: str | None = None
    positionals: list[str] = []
    args = iter(argv[1:])
    options_done = False
    for arg in args:
        if options_done or arg == "-" or not arg.startswith("-"):
            positionals.append(arg)
        elif arg == "--":
            options_done = True
        elif arg.startswith("--"):
            name, eq, value = arg.partition("=")
            if name in _NO_PATTERN:
                return None
            if name in value_long:
                if not eq:
                    value = next(args, None)
                    if value is None:
                        return None
                if name == "--regexp" and pattern is None:
                    pattern = value
            elif name not in _FLAG_LONG:
                return None
        else:
            letters = arg[1:]
            for i, letter in enumerate(letters):
                if letter == "f":
                    return None
                if letter in value_short:
                    value = letters[i + 1 :] or next(args, None)
                    if value is None:
                        return None
                    if letter == "e" and pattern is None:
                        pattern = value
                    break
    if pattern is None:
        if not positionals:
            return None
        pattern, positionals = positionals[0], positionals[1:]
    return pattern, positionals


def _subshell(command: str) -> bool:
    """Whether an *unquoted* paren or brace appears: a subshell, group or
    expansion that moves the search somewhere this cannot follow. Quoted ones
    are pattern text — `grep "check_version()"` is a lookup, not a subshell."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();&|{}")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return True
    return any(set(t) <= _PUNCTUATION and set(t) & _GROUPING for t in tokens)


def bash_search_pattern(command: str, repo_root: Path, cwd: Path) -> str | None:
    """The raw pattern of the first executed search over the repository, or None.

    Tracks a plain `cd <dir>` before the search. Anything that moves the shell
    somewhere this cannot place — a bare `cd`, `cd -`, `~`, a variable, a
    subshell, `pushd` — makes the whole command unknown, and unknown is silent.
    """
    segments = _segments(command)
    if segments is None or _subshell(command):
        return None
    here = cwd
    for argv, piped in segments:
        if not argv:
            continue
        name = argv[0].rsplit("/", 1)[-1]
        if name in {"pushd", "popd"}:
            return None
        if name == "cd":
            if len(argv) != 2 or argv[1] == "-" or _unresolvable(argv[1]):
                return None
            here = here / argv[1]
            continue
        if name not in SEARCH_TOOLS:
            continue
        if piped:
            return None
        parsed = _parse_search(argv)
        if parsed is None:
            return None
        pattern, paths = parsed
        if any(_unresolvable(p) for p in paths):
            return None
        targets = [here / p for p in paths] if paths else [here]
        if not all(is_inside(t, repo_root) for t in targets):
            return None
        return pattern
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
            if not is_inside(cwd / path, repo_root):
                return None
        return identifier(pattern)
    if tool_name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return None
        pattern = bash_search_pattern(command, repo_root, cwd)
        return identifier(pattern) if pattern is not None else None
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


# Edges that describe where a symbol lives rather than how it is used. A file
# node `contains` everything in it and would top any raw degree ranking.
_STRUCTURAL_RELATIONS = frozenset({"contains", "method", "rationale_for", "defines"})


def hubs(graph: dict, limit: int = 5) -> list[tuple[str, str]]:
    """The `limit` highest-degree definitions, as (label, `file:line`)."""
    raw_nodes = graph.get("nodes")
    raw_links = graph.get("links")
    nodes = {
        n["id"]: n
        for n in (raw_nodes if isinstance(raw_nodes, list) else [])
        if isinstance(n, dict) and isinstance(n.get("id"), str) and _is_definition(n)
    }
    degree: dict[str, int] = {}
    for link in raw_links if isinstance(raw_links, list) else []:
        if not isinstance(link, dict) or link.get("relation") in _STRUCTURAL_RELATIONS:
            continue
        for end in (link.get("source"), link.get("target")):
            if isinstance(end, str) and end in nodes:
                degree[end] = degree.get(end, 0) + 1
    ranked = sorted(degree, key=lambda nid: (-degree[nid], nodes[nid]["label"]))[:limit]
    return [(nodes[nid]["label"], _location(nodes[nid])) for nid in ranked]
