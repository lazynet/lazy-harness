#!/usr/bin/env python3
"""SessionStart hook: inject project context.

Outputs JSON with `hookSpecificOutput` for Claude Code. Sections composed:

    ## Git             — branch, last commit, dirty status
    ## LazyNorth       — strategic compass (universal + per-profile)
    ## Last session    — most recent exported session for this project
    ## Handoff         — handoff.md + pre-compact-summary.md
    ## Proposals       — claude-md.proposal.md from compound-loop
    ## Curated memory  — canonical per-project MEMORY.md
    ## Recent history  — decisions.jsonl + failures.jsonl tails

Read-only. Always exits 0. Logs to `<agent runtime dir>/logs/hooks.log`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import yaml

from lazy_harness.agents.base import HookDecision, HookEvent

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)) if p else Path()


def _run_git(*args: str, cwd: Path | None = None) -> str:
    try:
        r = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(cwd) if cwd else None,
        )
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #


def git_context(cwd: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            check=True,
            cwd=str(cwd),
        )
        if b"true" not in r.stdout:
            return ""
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""

    parts: list[str] = []
    branch = _run_git("branch", "--show-current", cwd=cwd)
    parts.append(f"Branch: {branch or 'detached'}")

    last_commit = _run_git("log", "-1", "--format=%h %s", cwd=cwd)
    if last_commit:
        parts.append(f"Last commit: {last_commit}")

    status = _run_git("status", "--short", cwd=cwd)
    if status:
        lines = status.splitlines()
        modified = sum(1 for ln in lines if ln and not ln.lstrip().startswith("?"))
        untracked = sum(1 for ln in lines if ln.lstrip().startswith("?"))
        summary: list[str] = []
        if modified:
            summary.append(f"{modified} modified")
        if untracked:
            summary.append(f"{untracked} untracked")
        if summary:
            parts.append(f"Uncommitted: {', '.join(summary)}")
    return "\n".join(parts)


def last_session_context(
    sessions_dir: Path,
    project_name: str,
    *,
    identity: str = "",
    project_root: Path | None = None,
) -> str:
    """Read the latest export with exact project and exporting-identity metadata.

    Legacy display names and classified profile labels cannot establish scope.
    Local project keys additionally need their main checkout's absolute path.
    """
    if not sessions_dir.is_dir() or "/" not in project_name or not identity:
        return ""

    best_path: Path | None = None
    best_mtime = 0.0
    for md in sessions_dir.rglob("*.md"):
        try:
            with open(md) as f:
                head = f.read(16384)
            if not head.startswith("---\n") or "\n---\n" not in head[4:]:
                continue
            meta = yaml.safe_load(head[4:].split("\n---\n", 1)[0])
            if not isinstance(meta, dict):
                continue
            if meta.get("project_key") != project_name or meta.get("source_identity") != identity:
                continue
            if project_name.startswith("local/") and (
                project_root is None or meta.get("project_root") != str(project_root.resolve())
            ):
                continue
            mtime = md.stat().st_mtime
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best_path = md

    if best_path is None:
        return ""

    try:
        text = best_path.read_text()
    except (OSError, UnicodeError):
        return ""

    date_val = ""
    messages_val = ""
    for line in text.splitlines():
        if line.startswith("date:"):
            date_val = line.split(":", 1)[1].strip()
        elif line.startswith("messages:"):
            messages_val = line.split(":", 1)[1].strip()
        if date_val and messages_val:
            break

    first_user_msg = ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## User"):
            # First non-empty line after the heading
            for j in range(i + 1, len(lines)):
                candidate = lines[j].strip()
                if candidate:
                    first_user_msg = candidate
                    break
            break
    if len(first_user_msg) > 80:
        first_user_msg = first_user_msg[:77] + "..."

    parts = [f"Last session: {date_val or 'unknown'} ({messages_val or '?'} messages)"]
    if first_user_msg:
        parts.append(f'Working on: "{first_user_msg}"')
    return "\n".join(parts)


def _strip_intro_lines(text: str, extra_skip_prefixes: tuple[str, ...] = ()) -> list[str]:
    """Mimic the bash sed for LazyNorth body extraction:
    strip frontmatter, H1 title, specific intro lines, and blank lines."""
    out: list[str] = []
    in_fm = False
    fm_done = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if not fm_done and not in_fm:
                in_fm = True
                continue
            if in_fm:
                in_fm = False
                fm_done = True
                continue
        if in_fm:
            continue
        if stripped.startswith("# "):
            continue
        if any(stripped.startswith(p) for p in extra_skip_prefixes):
            continue
        if not stripped:
            continue
        out.append(line)
    return out


def lazynorth_context(
    lazynorth_root: Path,
    universal_doc: str,
    profile_doc: str,
    universal_limit: int = 20,
    profile_limit: int = 15,
) -> str:
    if not lazynorth_root.is_dir():
        return ""

    sections: list[str] = []

    universal_path = lazynorth_root / universal_doc
    if universal_path.is_file():
        try:
            body = _strip_intro_lines(
                universal_path.read_text(),
                extra_skip_prefixes=("Brújula estratégica",),
            )[:universal_limit]
            if body:
                sections.append("\n".join(body))
        except OSError:
            pass

    if profile_doc:
        profile_path = lazynorth_root / profile_doc
        if profile_path.is_file():
            try:
                body = _strip_intro_lines(
                    profile_path.read_text(),
                    extra_skip_prefixes=("Foco trimestral",),
                )[:profile_limit]
                if body:
                    sections.append("\n".join(body))
            except OSError:
                pass

    return "\n\n".join(sections)


_STALENESS_WINDOW_SECONDS = 300


def _parse_handoff_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a handoff.md into (metadata, body_without_frontmatter).

    Returns an empty metadata dict if the file has no leading `---` block.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta_block = text[4:end]
    body = text[end + 5 :]
    meta: dict[str, str] = {}
    for line in meta_block.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, body


def _classify_handoff_staleness(meta: dict[str, str], latest_session: Path | None) -> str | None:
    """Return a reason string if the handoff is stale, None if fresh.

    Fresh means: the handoff's session_id matches the latest session JSONL on
    disk AND that JSONL has not grown past `_STALENESS_WINDOW_SECONDS` beyond
    the recorded source_mtime.
    """
    handoff_sid = meta.get("session_id", "")
    if latest_session is None:
        return f"No session JSONL found on disk for handoff {handoff_sid[:8]}."
    latest_sid = latest_session.stem
    if handoff_sid != latest_sid:
        return (
            f"Last written for session {handoff_sid[:8]}. "
            f"Most recent session on disk: {latest_sid[:8]}."
        )
    try:
        source_mtime = float(meta.get("source_mtime", "0") or 0)
    except ValueError:
        source_mtime = 0.0
    try:
        current_mtime = latest_session.stat().st_mtime
    except OSError:
        return None  # can't tell — trust it
    delta = current_mtime - source_mtime
    if delta > _STALENESS_WINDOW_SECONDS:
        return (
            f"Session {handoff_sid[:8]} grew {delta:.0f}s "
            f"past the handoff snapshot (window={_STALENESS_WINDOW_SECONDS}s)."
        )
    return None


def _latest_session_jsonl(sessions_dir: Path) -> Path | None:
    if not sessions_dir.is_dir():
        return None
    jsonl_files = [p for p in sessions_dir.glob("*.jsonl") if p.is_file()]
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def handoff_context(memory_dir: Path) -> str:
    parts: list[str] = []

    handoff = memory_dir / "handoff.md"
    if handoff.is_file():
        try:
            raw = handoff.read_text()
        except OSError:
            raw = ""
        if raw:
            meta, body = _parse_handoff_frontmatter(raw)
            body = body.strip()
            if not meta:
                parts.append(
                    "(legacy handoff — no provenance metadata, treat with caution)\n" + body
                )
            else:
                sessions_dir = memory_dir.parent
                latest = _latest_session_jsonl(sessions_dir)
                stale_reason = _classify_handoff_staleness(meta, latest)
                if stale_reason is None:
                    parts.append(body)
                else:
                    parts.append(
                        "⚠️ Handoff may be stale.\n"
                        f"{stale_reason}\n"
                        "Do NOT trust the items below as current. "
                        "Ask the user what's actually pending.\n\n"
                        "--- stale content below ---\n" + body
                    )

    pre_compact = memory_dir / "pre-compact-summary.md"
    if pre_compact.is_file():
        try:
            compact_text = pre_compact.read_text()
            filtered = [
                ln for ln in compact_text.splitlines() if not ln.lstrip().startswith("<!--")
            ]
            body = "\n".join(filtered).strip()
            if body:
                parts.append(f"Pre-compact context:\n{body}")
        except OSError:
            pass

    return "\n\n".join(p for p in parts if p)


def proposals_context(memory_dir: Path) -> str:
    """Return body of claude-md.proposal.md (compound-loop output for the human to
    review), with the HTML comment header stripped. Empty string when no file."""
    proposal_file = memory_dir / "claude-md.proposal.md"
    if not proposal_file.is_file():
        return ""
    try:
        raw = proposal_file.read_text()
    except OSError:
        return ""
    filtered = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("<!--")]
    return "\n".join(filtered).strip()


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_PROPOSAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

#: Said once, read by both callers. The halt notice and the budget-pressure
#: fallback are the same sentence: a reader who sees one and not the other
#: would otherwise get two different accounts of the same queue.
_QUEUE_FULL_TAIL = "the queue is full, so no new ones are being recorded. Drain it"


def _pending_summary(memory_dir: Path) -> tuple[int, str]:
    """(count, oldest date) for the pending queue, counted the way the CLI
    numbers it. `(0, "")` when there is nothing to report."""
    from lazy_harness.core.proposals import parse_proposals

    proposal_file = memory_dir / "claude-md.proposal.md"
    if not proposal_file.is_file():
        return 0, ""
    try:
        raw = proposal_file.read_text()
    except OSError:
        return 0, ""
    pending = parse_proposals(raw)
    dates = [p.timestamp[:10] for p in pending if _PROPOSAL_DATE_RE.match(p.timestamp)]
    if not pending or not dates:
        return 0, ""
    return len(pending), min(dates)


def proposals_summary_line(memory_dir: Path, max_pending: int | None = None) -> str:
    """One-line reminder that pending claude-md proposals exist, so the
    self-healing channel stays visible even when the full section is dropped
    under budget pressure.

    Counting goes through the same parser `lh memory proposals list` numbers
    with: a reader that counts a bullet the CLI declines to number reports a
    queue the user cannot drain. Archived HTML comment blocks do not count.

    At or above `max_pending` the compound loop has stopped emitting proposals,
    so the line says that rather than only asking for a review — the halt is
    the part that costs something. Empty string when nothing is pending.
    """
    count, oldest = _pending_summary(memory_dir)
    if not count:
        return ""
    head = f"⚠ {count} claude-md proposal(s) pending (oldest {oldest})"
    if max_pending is not None and count >= max_pending:
        return f"{head} — {_QUEUE_FULL_TAIL}: lh memory proposals"
    return f"{head} — review: lh memory proposals"


def proposals_halt_notice(memory_dir: Path, max_pending: int | None) -> str:
    """The same line, but only once the queue is at the cap.

    The budget-pressure fallback fires only when the proposals section is
    dropped. A halted producer has to be visible in the ordinary case too —
    the whole point of the cap is that stopping is noticed.
    """
    if max_pending is None:
        return ""
    count, _ = _pending_summary(memory_dir)
    if not count or count < max_pending:
        return ""
    return proposals_summary_line(memory_dir, max_pending)


def _jsonl_tail_summaries(path: Path, limit: int, include_prevention: bool) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text().strip().splitlines()[-limit:]
    except OSError:
        return []
    out: list[str] = []
    for line in lines:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        summary = d.get("summary", "?")
        if include_prevention:
            prevention = d.get("prevention", "")
            out.append(f"- {summary} → {prevention}" if prevention else f"- {summary}")
        else:
            out.append(f"- {summary}")
    return out


def episodic_context(memory_dir: Path, limit: int = 3) -> str:
    parts: list[str] = []

    decisions = _jsonl_tail_summaries(
        memory_dir / "decisions.jsonl", limit, include_prevention=False
    )
    if decisions:
        parts.append("Recent decisions:\n" + "\n".join(decisions))

    failures = _jsonl_tail_summaries(memory_dir / "failures.jsonl", limit, include_prevention=True)
    if failures:
        parts.append("Recent failures:\n" + "\n".join(failures))

    return "\n".join(parts)


def curated_memory_context(memory_dir: Path, max_chars: int) -> str:
    source = memory_dir / "MEMORY.md"
    if max_chars <= 0:
        return ""
    source_text = str(source)
    source_limit = max(1, max_chars // 3)
    if len(source_text) > source_limit:
        source_text = "…" + source_text[-(source_limit - 1) :]
    prefix = f"## Curated memory\nSource: {source_text}\n"
    try:
        with source.open(encoding="utf-8") as memory_file:
            content = memory_file.read(max_chars + 1)
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeError):
        return (prefix + "[unreadable or invalid MEMORY.md]")[:max_chars]

    if not content:
        return ""
    available = max_chars - len(prefix)
    if available <= 0:
        return (prefix[: max_chars - 1] + "…") if max_chars > 1 else "…"
    if len(content) <= available:
        return prefix + content
    notice = "\n[curated memory truncated]"
    if available <= len(notice):
        return prefix + notice[:available]
    return prefix + content[: available - len(notice)] + notice


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #


def _profile_for_config_dir(config_dir: str, profiles: dict[str, object]) -> tuple[str, str]:
    """Returns (profile_name, lazynorth_doc) by matching the agent's
    config-dir env var against each profile's config_dir. Returns ('', '')
    if no match."""
    if not config_dir:
        return ("", "")
    expanded = str(Path(os.path.expanduser(config_dir)).resolve()) if config_dir else ""
    for name, entry in profiles.items():
        entry_dir = getattr(entry, "config_dir", "") or ""
        if not entry_dir:
            continue
        try:
            if str(Path(os.path.expanduser(entry_dir)).resolve()) == expanded:
                return (name, getattr(entry, "lazynorth_doc", "") or "")
        except OSError:
            continue
    return ("", "")


def _join_sections(*sections: str) -> str:
    return "\n\n".join(s for s in sections if s)


def _compose_banner(git_ctx: str, last_session_ctx: str, handoff_ctx: str) -> str:
    parts: list[str] = []
    branch_match = re.search(r"^Branch:\s*(\S+)", git_ctx, re.MULTILINE)
    if branch_match:
        parts.append(f"on {branch_match.group(1)}")
    if last_session_ctx:
        first_line = last_session_ctx.splitlines()[0]
        parts.append(first_line)
    if handoff_ctx:
        parts.append("has handoff notes")
    if not parts:
        return "Session context loaded (new project)"
    return "Session context loaded: " + " | ".join(parts)


def _truncate_body(
    max_chars: int,
    git_section: str,
    north_section: str,
    session_section: str,
    handoff_section: str,
    episodic_section: str,
    suggest_section: str = "",
    proposals_section: str = "",
    proposals_summary: str = "",
    graphify_section_text: str = "",
    repo_map_section: str = "",
    curated_section: str = "",
) -> str:
    """Drop sections in priority order until body fits: episodic → suggest →
    proposals → north → code structure → repo map → handoff. Proposals (compound-loop
    suggestions to merge into CLAUDE.md) sit between handoff and vault notes in
    document order, and are dropped after vault notes since they describe past
    work rather than pending action. The code-structure summary outranks all of
    them: it is a compact map of the repo the session is about to edit, and it
    is the whole reason the graph is generated. When the proposals section is
    dropped and ``proposals_summary`` is non-empty, that one-liner is emitted
    alongside the truncation banner so pending proposals are never silently
    hidden."""

    def assemble(
        *,
        north: bool,
        handoff: bool,
        proposals: bool,
        suggest: bool,
        episodic: bool,
        graphify: bool,
        repo_map: bool,
    ) -> str:
        return _join_sections(
            curated_section,
            git_section,
            repo_map_section if repo_map else "",
            north_section if north else "",
            session_section,
            handoff_section if handoff else "",
            graphify_section_text if graphify else "",
            proposals_section if proposals else "",
            suggest_section if suggest else "",
            episodic_section if episodic else "",
        )

    keep = {
        "north": True,
        "handoff": True,
        "proposals": True,
        "suggest": True,
        "episodic": True,
        "graphify": True,
        "repo_map": True,
    }
    body = assemble(**keep)
    if len(body) <= max_chars:
        return body

    dropped: list[str] = []
    summary_line = ""
    # (flag, banner label, section text) in drop order.
    order = [
        ("episodic", "Recent history", episodic_section),
        ("suggest", "Relevant vault notes", suggest_section),
        ("proposals", "Proposals to review", proposals_section),
        ("north", "LazyNorth", north_section),
        ("graphify", "Code structure", graphify_section_text),
        ("repo_map", "Repo map", repo_map_section),
        ("handoff", "Handoff from last session", handoff_section),
    ]
    for flag, label, text in order:
        # "Recent history" is always named, matching the historical banner even
        # when the section was empty to begin with.
        if text or flag == "episodic":
            dropped.append(label)
        if flag == "proposals" and proposals_section:
            summary_line = proposals_summary
        keep[flag] = False
        body = assemble(**keep)
        if len(body) <= max_chars:
            return _prepend_truncation_banner(body, dropped, max_chars, summary_line)

    return _prepend_truncation_banner(body, dropped, max_chars, summary_line)


def _cap_body(body: str, max_chars: int, curated_priority: str = "") -> str:
    if max_chars <= 0:
        return ""
    if len(body) <= max_chars:
        return body
    notice = "[context truncated to max_body_chars]"
    proposal_summary = next((line for line in body.splitlines() if line.startswith("⚠ ")), "")
    if curated_priority:
        compact = ""
        if proposal_summary:
            match = re.search(r"⚠ (\d+) claude-md proposal", proposal_summary)
            if match:
                compact = f"⚠ {match.group(1)} proposal(s) pending"
        candidate = _join_sections(curated_priority, "[truncated]", compact)
        if len(candidate) <= max_chars:
            return candidate
        candidate = _join_sections(curated_priority, notice)
        if len(candidate) <= max_chars:
            return candidate
    compact_notice = "[truncated]"
    if proposal_summary and len(compact_notice) + 1 + len(proposal_summary) <= max_chars:
        return f"{compact_notice}\n{proposal_summary}"
    if max_chars <= len(notice):
        return notice[:max_chars]
    kept = body[: max_chars - len(notice) - 1]
    if "\n" in kept and not kept.endswith("\n"):
        kept = kept.rsplit("\n", 1)[0]
    return kept + "\n" + notice


def _prepend_truncation_banner(
    body: str, dropped: list[str], max_chars: int, extra_line: str = ""
) -> str:
    banner = f"[truncated: dropped {', '.join(dropped)} to fit {max_chars}-char budget]"
    if extra_line:
        banner = f"{banner}\n{extra_line}"
    return f"{banner}\n\n{body}"


def graphify_section(graphify_dir: Path, repo_root: Path) -> str:
    """Either a staleness banner or a content summary, depending on freshness.

    Returns "" when `graphify-out/graph.json` does not exist (no graph yet).
    Stale (mtime < HEAD timestamp) → "## Notice" banner pointing at /graphify.
    Fresh → "## Code structure": the five most connected symbols with their
    locations, example commands built from them, and when the graph beats grep.
    A graph with no code symbols falls back to its node and edge counts.

    Fail-soft on any IO or parse error — returns "".
    """
    graph_json = graphify_dir / "graph.json"
    if not graph_json.is_file():
        return ""

    try:
        graph_mtime = graph_json.stat().st_mtime
    except OSError:
        return ""

    head_ts: float | None = None
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            head_ts = float(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        head_ts = None

    if head_ts is not None and graph_mtime < head_ts:
        from datetime import datetime as _dt

        head_date = _dt.fromtimestamp(head_ts).strftime("%Y-%m-%d")
        graph_date = _dt.fromtimestamp(graph_mtime).strftime("%Y-%m-%d")
        return (
            f"## Notice\n"
            f"graphify-out/ is stale (last built {graph_date}, HEAD {head_date}). "
            f"Run /graphify to refresh."
        )

    try:
        data = json.loads(graph_json.read_text())
    except (json.JSONDecodeError, OSError, ValueError):
        return ""

    if not isinstance(data, dict):
        return ""
    nodes = data.get("nodes", [])
    links = data.get("links", data.get("edges", []))
    if not isinstance(nodes, list):
        return ""

    from lazy_harness.knowledge.graph_assist import hubs

    top = hubs(data)
    if not top:
        link_count = len(links) if isinstance(links, list) else 0
        return f"## Code structure\n- {len(nodes)} nodes · {link_count} edges"

    lines = ["## Code structure", "Most connected symbols:"]
    lines += [f"- {label} — {location}" for label, location in top]
    labels = [label for label, _ in top]
    examples = [f'graphify explain "{labels[0]}"']
    if len(labels) > 1:
        examples.append(f'graphify path "{labels[0]}" "{labels[1]}"')
    examples.append(f'graphify query "what depends on {labels[-1]}"')
    lines.append("Examples: " + " · ".join(f"`{e}`" for e in examples))
    lines.append(
        "The graph answers who calls X, what breaks if Y changes and which docs "
        "name Z faster than grep does."
    )
    return "\n".join(lines)


def repo_map_context(cwd: Path, doc: Path, scope: Path | None, max_chars: int = 1200) -> str:
    """Return the repo-map doc when `cwd` sits inside `scope`, else "".

    Opt-in by design: `scope=None` disables the section, so sessions outside the
    declared tree never pay for it. Both paths are resolved before comparison, so
    a cwd reached through a symlink still matches and a sibling that merely
    shares the scope's name prefix does not.

    The doc is capped at `max_chars` — measured in characters because that is the
    unit `max_body_chars` spends, and a real repo map runs several times the whole
    body budget. Uncapped it survives to second-to-last in the drop order and
    starves every other section before dropping itself. The cut lands on a line
    boundary so a truncated map never invents a half-written repo name, and the
    remainder is announced rather than silently dropped.

    Fail-soft on a missing, unreadable or non-UTF-8 doc — returns "".
    """
    if scope is None:
        return ""
    try:
        if not cwd.resolve().is_relative_to(scope.resolve()):
            return ""
        text = doc.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return ""

    if len(text) <= max_chars:
        return text

    kept: list[str] = []
    used = 0
    for line in text.splitlines():
        if used + len(line) > max_chars:
            break
        kept.append(line)
        used += len(line) + 1
    note = f"[repo map truncated at {max_chars} chars — raise repo_map_max_chars for more]"
    return "\n\n".join(filter(None, ["\n".join(kept), note]))


def qmd_suggest_context(
    query_text: str, top_k: int = 3, timeout: int = 5, *, collection: str = ""
) -> str:
    """Top-K vault notes related to the current task as markdown.

    Returns "" when the query is blank or qmd has no hits — caller should
    omit the section entirely. Fail-soft: never raises.
    """
    query_text = query_text.strip()
    if not query_text or not collection:
        return ""
    from lazy_harness.knowledge import qmd

    hits = qmd.query(query_text, limit=top_k, timeout=timeout, collection=collection)
    if not hits:
        return ""
    lines: list[str] = []
    for hit in hits:
        title = hit.title or hit.file
        lines.append(f"- [{title}]({hit.file})")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #


def main(event: HookEvent) -> HookDecision:
    try:
        from lazy_harness.core.config import ConfigError, load_config
        from lazy_harness.core.paths import config_file
        from lazy_harness.hooks.builtins._shared import (
            _project_dir_of,
            agent_dir_for,
            knowledge_root_for,
            make_log,
        )
        from lazy_harness.hooks.builtins._shared import memory_dir as shared_memory_dir
    except ImportError:
        # Broken/uninstalled package: silently no-op, never block the agent.
        return HookDecision()

    _log = make_log("session-context")

    # A payload with no `cwd` parses as `Path(".")`. The process directory is
    # what this hook read before the runner, and it is the same directory the
    # agent declares whenever it declares one at all.
    cwd = event.cwd if event.cwd != Path(".") else Path.cwd()

    cf = config_file()
    cfg = None
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError:
            cfg = None

    # Per profile, not per machine: `--profile` is in the deployed command, and
    # both halves of this answer used to be read from the global `[agent].type`.
    agent, agent_dir = agent_dir_for(cfg, event.profile)
    subdirs = agent.session_dirs()
    log_file = agent_dir / (subdirs.get("logs") or "logs") / "hooks.log"
    # Config loads before the first line is written, rather than after. The
    # bootstrap resolution this replaces went through a hardcoded
    # `get_agent("claude-code")`, so `fired` landed in whatever directory the
    # global agent named while `injected` below landed in the profile's own --
    # one hook's audit trail split across two live profiles. Nothing in tests,
    # specs or docs reads this line's timing; the two consumers of the log
    # (`lh status hooks` and `docs/how/hooks.md`) parse its format.
    #
    # An absent config and a `ConfigError` still resolve globally, and
    # correctly so: the profile -> config_dir mapping lives in the file that
    # did not load. `agent_dir_for`'s docstring owns that limit.
    #
    # Only those two. Any other failure of `load_config` -- `PermissionError`,
    # `OSError`, a decode error -- escapes this function, and then neither line
    # is written rather than one landing globally. `run_hook`'s blanket handler
    # still reports it on stderr at exit 0, so the failure stays visible; what
    # is lost is the persistent record, which was being written to the wrong
    # profile anyway.
    _log(log_file, f"fired cwd={cwd}")

    # Sections. Prefer the project dir the agent declared over one derived from
    # cwd — the agent's encoding of cwd has changed across releases.
    from lazy_harness.agents.session_paths import session_path, session_subdir

    sessions_root = session_path(agent, agent_dir, "sessions")
    if sessions_root is None:
        return HookDecision()
    project_dir = _project_dir_of(event.transcript_path)
    if project_dir is None:
        encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
        project_dir = sessions_root / encoded
    # Sessions stay in the agent's project dir; distilled memory does not. That
    # directory is named after the checkout's absolute path, so the same
    # repository on two machines injected two different MEMORY.md files — one
    # of them empty, with nothing to say so.
    memory_dir = shared_memory_dir(
        event.transcript_path,
        agent_dir=agent_dir,
        sessions_subdir=session_subdir(agent, "sessions"),
        cwd=cwd,
        knowledge_root=knowledge_root_for(cfg),
    )

    git_ctx = git_context(cwd)

    last_session_ctx = ""
    north_ctx = ""
    if cfg is not None:
        from lazy_harness.knowledge.directory import sessions_dir as knowledge_sessions_dir
        from lazy_harness.knowledge.marker import MarkerError, resolve_root

        try:
            sessions_dir = knowledge_sessions_dir(resolve_root(cfg.knowledge.root or None))
        except MarkerError:
            sessions_dir = None
        if (
            cfg.context_inject.enabled
            and cfg.context_inject.last_session_enabled
            and sessions_dir
            and sessions_dir.is_dir()
        ):
            from lazy_harness.core.profile_identity import profile_identity
            from lazy_harness.core.project_identity import main_repo_root, project_key

            entry = cfg.profiles.items.get(event.profile)
            last_session_ctx = last_session_context(
                sessions_dir,
                project_key(cwd),
                identity=profile_identity(event.profile, entry) if entry is not None else "",
                project_root=main_repo_root(cwd) or cwd,
            )

        if cfg.lazynorth.enabled and cfg.lazynorth.path:
            env_var = agent.env_var()
            _, profile_doc = _profile_for_config_dir(
                os.environ.get(env_var, "") if env_var else "",
                cfg.profiles.items,
            )
            north_ctx = lazynorth_context(
                _expand(cfg.lazynorth.path),
                cfg.lazynorth.universal_doc,
                profile_doc,
            )

    handoff_ctx = handoff_context(memory_dir)
    proposals_ctx = proposals_context(memory_dir)
    proposals_summary = ""
    if cfg is None or cfg.context_inject.proposals_summary:
        proposals_summary = proposals_summary_line(
            memory_dir,
            max_pending=(cfg.compound_loop.max_pending_proposals if cfg is not None else None),
        )
    episodic_ctx = episodic_context(memory_dir)

    suggest_ctx = ""
    if cfg is not None and cfg.context_inject.qmd_suggest_enabled:
        branch_name = ""
        if git_ctx:
            for line in git_ctx.splitlines():
                if line.startswith("Branch:"):
                    branch_name = line.split(":", 1)[1].strip()
                    break
        entry = cfg.profiles.items.get(event.profile)
        if branch_name and entry is not None:
            suggest_ctx = qmd_suggest_context(
                branch_name, cfg.context_inject.qmd_suggest_top_k, collection=entry.qmd_collection
            )

    graphify_ctx = ""
    if cfg is None or cfg.context_inject.graphify_surface_enabled:
        graphify_ctx = graphify_section(cwd / "graphify-out", cwd)

    repo_map_ctx = ""
    if cfg is not None and cfg.context_inject.repo_map_scope:
        repo_map_ctx = repo_map_context(
            cwd,
            agent_dir / cfg.context_inject.repo_map_doc,
            _expand(cfg.context_inject.repo_map_scope),
            cfg.context_inject.repo_map_max_chars,
        )

    # Sections wrapped with markdown headings
    git_section = f"## Git\n{git_ctx}" if git_ctx else ""
    session_section = f"## Last session\n{last_session_ctx}" if last_session_ctx else ""
    handoff_section = f"## Handoff from last session\n{handoff_ctx}" if handoff_ctx else ""
    proposals_section = ""
    if proposals_ctx:
        halt = proposals_halt_notice(
            memory_dir,
            cfg.compound_loop.max_pending_proposals if cfg is not None else None,
        )
        lead = f"{halt}\n\n" if halt else ""
        proposals_section = f"## Proposals to review\n{lead}{proposals_ctx}"
    episodic_section = f"## Recent history\n{episodic_ctx}" if episodic_ctx else ""
    north_section = f"## LazyNorth\n{north_ctx}" if north_ctx else ""
    suggest_section = f"## Relevant vault notes\n{suggest_ctx}" if suggest_ctx else ""
    repo_map_section = f"## Repo map\n{repo_map_ctx}" if repo_map_ctx else ""

    max_chars = cfg.context_inject.max_body_chars if cfg is not None else 3000
    curated_ctx = curated_memory_context(memory_dir, min(12000, max_chars // 2))
    body = _truncate_body(
        max_chars,
        git_section,
        north_section,
        session_section,
        handoff_section,
        episodic_section,
        suggest_section=suggest_section,
        proposals_section=proposals_section,
        proposals_summary=proposals_summary,
        graphify_section_text=graphify_ctx,
        repo_map_section=repo_map_section,
        curated_section=curated_ctx,
    )
    if not body:
        body = "New project, no prior context."
    body = _cap_body(body, max_chars, curated_priority=curated_ctx)

    banner = _cap_body(_compose_banner(git_ctx, last_session_ctx, handoff_ctx), min(200, max_chars))

    _log(log_file, f"injected {len(body)} chars, banner={banner[:80]}")
    # The banner is a top-level `systemMessage` and the body is nested under
    # `additionalContext`; which field goes where is the adapter's knowledge
    # now, and it is not guesswork — nested, the banner parsed and was
    # discarded, so the body arrived and the banner never did.
    return HookDecision(additional_context=body, system_message=banner)
