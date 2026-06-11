"""Compound-loop evaluator — distills session learnings via an LLM backend.

Port of lazy-claudecode/scripts/hooks/compound-loop-worker. Runs as a
background worker off a file queue: each task points at a session JSONL,
and the worker invokes the configured LLM backend (ADR-033; default headless
`claude -p`) to extract decisions, failures, learnings, and handoff items,
persisting to JSONL + markdown.

The module is intentionally flat so each pure function is testable in
isolation without mocking a class.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lazy_harness.core.config import CompoundLoopConfig
from lazy_harness.llm.base import LLMBackend, LLMBackendError
from lazy_harness.llm.claude import ClaudeBackend

_INTERACTIVE_MARKERS = ("permission-mode", "last-prompt")
_INTERACTIVE_SCAN_LINES = 10

_INSIGHT_PATTERN = re.compile(r"★ Insight ─+\s*\n(.*?)\n─+", re.DOTALL)


@dataclass(frozen=True)
class Insight:
    """One verbatim `★ Insight ─` block captured from an assistant message."""

    body: str
    message_index: int
    timestamp: str
    session_id: str
    content_hash: str


def _normalize_for_hash(body: str) -> str:
    return " ".join(body.split())


def _content_hash(body: str) -> str:
    return hashlib.sha256(_normalize_for_hash(body).encode("utf-8")).hexdigest()[:16]


def _assistant_text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def extract_insights(session_jsonl: Path, since_index: int = 0) -> list[Insight]:
    """Stream a session JSONL and return one `Insight` per `★ Insight ─` block.

    Only assistant messages are scanned — user messages with the same marker
    are ignored deliberately so the human cannot fabricate canonical insights
    by copy-pasting the markup.
    """
    insights: list[Insight] = []
    session_id = session_jsonl.stem
    try:
        with open(session_jsonl) as f:
            for index, line in enumerate(f):
                if index < since_index:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if record.get("type") != "assistant":
                    continue
                text = _assistant_text(record.get("message", {}))
                ts = record.get("timestamp", "") or ""
                for match in _INSIGHT_PATTERN.finditer(text):
                    body = match.group(1)
                    insights.append(
                        Insight(
                            body=body,
                            message_index=index,
                            timestamp=ts,
                            session_id=session_id,
                            content_hash=_content_hash(body),
                        )
                    )
    except OSError:
        return []
    return insights


def _insight_date(timestamp: str) -> datetime:
    if timestamp:
        try:
            return datetime.fromisoformat(timestamp)
        except ValueError:
            pass
    return datetime.now()


def _format_insight_md(insight: Insight) -> str:
    return (
        "---\n"
        f"session_id: {insight.session_id}\n"
        f"message_index: {insight.message_index}\n"
        f"timestamp: {insight.timestamp}\n"
        "source: assistant\n"
        f"content_hash: {insight.content_hash}\n"
        "---\n"
        f"{insight.body}\n"
    )


def _existing_insight_hashes(insights_dir: Path) -> set[str]:
    hashes: set[str] = set()
    if not insights_dir.is_dir():
        return hashes
    for path in insights_dir.rglob("*.md"):
        try:
            text = path.read_text()
        except OSError:
            continue
        match = re.search(r"^content_hash:\s*(\S+)", text, re.MULTILINE)
        if match:
            hashes.add(match.group(1))
    return hashes


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def persist_insights(memory_dir: Path, insights: list[Insight]) -> list[Path]:
    """Write each Insight to `memory_dir/insights/YYYY-MM/<filename>.md`.

    Idempotent across re-runs: insights whose `content_hash` already exists on
    disk are skipped. Returns the list of paths actually written.
    """
    if not insights:
        return []
    insights_dir = memory_dir / "insights"
    existing = _existing_insight_hashes(insights_dir)
    written: list[Path] = []
    for insight in insights:
        if insight.content_hash in existing:
            continue
        date = _insight_date(insight.timestamp)
        ym = date.strftime("%Y-%m")
        ymd = date.strftime("%Y-%m-%d")
        short = insight.session_id[:8]
        month_dir = insights_dir / ym
        month_dir.mkdir(parents=True, exist_ok=True)
        n = 1
        while (month_dir / f"{ymd}-{short}-{n}.md").exists():
            n += 1
        path = month_dir / f"{ymd}-{short}-{n}.md"
        _atomic_write(path, _format_insight_md(insight))
        existing.add(insight.content_hash)
        written.append(path)
    return written


def _insight_cursor_path(memory_dir: Path) -> Path:
    return memory_dir / "insights" / ".cursor.json"


def _read_insight_cursor(memory_dir: Path, session_id: str) -> int:
    """Return the last processed insight message index for this session, or -1."""
    path = _insight_cursor_path(memory_dir)
    if not path.is_file():
        return -1
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, ValueError):
        return -1
    value = data.get(session_id, -1)
    return value if isinstance(value, int) else -1


def _write_insight_cursor(memory_dir: Path, session_id: str, last_index: int) -> None:
    path = _insight_cursor_path(memory_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, int] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text())
            if isinstance(existing, dict):
                data = {k: v for k, v in existing.items() if isinstance(v, int)}
        except (json.JSONDecodeError, OSError, ValueError):
            data = {}
    data[session_id] = last_index
    _atomic_write(path, json.dumps(data, sort_keys=True) + "\n")


def is_interactive_session(session_jsonl: Path) -> bool:
    """Interactive sessions emit a `permission-mode` or `last-prompt` record early.

    Headless `claude -p` sessions and subagents start with other types; we
    only want to evaluate actual user conversations. We scan a bounded prefix
    because Claude Code's session JSONL layout is not strictly ordered — the
    marker may sit on line 1 or a few lines down depending on session origin
    (fresh vs resumed).
    """
    try:
        with open(session_jsonl) as f:
            for _ in range(_INTERACTIVE_SCAN_LINES):
                line = f.readline()
                if not line:
                    return False
                try:
                    d = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if d.get("type") in _INTERACTIVE_MARKERS:
                    return True
        return False
    except OSError:
        return False


def _last_user_prompt(session_jsonl: Path) -> str | None:
    """Last user-typed text in the session, or None if there are none."""
    last: str | None = None
    try:
        with open(session_jsonl) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if d.get("type") != "user":
                    continue
                msg = d.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, str):
                    text = content.strip()
                    if text:
                        last = text
                elif isinstance(content, list):
                    parts = [
                        block.get("text", "").strip()
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    joined = "\n".join(p for p in parts if p)
                    if joined:
                        last = joined
    except OSError:
        return None
    return last


def _files_touched(session_jsonl: Path, limit: int = 20) -> list[str]:
    """File paths surfaced by assistant tool_use blocks (Edit/Write/Read)."""
    seen: list[str] = []
    seen_set: set[str] = set()
    try:
        with open(session_jsonl) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if d.get("type") != "assistant":
                    continue
                msg = d.get("message", {})
                content = msg.get("content", "")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    inp = block.get("input", {})
                    if not isinstance(inp, dict):
                        continue
                    path = inp.get("file_path") or inp.get("path") or ""
                    if not path or path in seen_set:
                        continue
                    seen.append(path)
                    seen_set.add(path)
    except OSError:
        return []
    return seen[-limit:]


def _current_branch(cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def write_slim_handoff(
    session_jsonl: Path,
    memory_dir: Path,
    cwd: str,
) -> bool:
    """Deterministic minimal handoff written when LLM evaluation is gated out.

    Captures branch, last user prompt verbatim, and files touched. Returns
    True if a handoff was written, False if there was nothing useful to record
    (no user prompts in the session). Overwrites any existing handoff.md.
    """
    last_prompt = _last_user_prompt(session_jsonl)
    if not last_prompt:
        return False

    branch = _current_branch(Path(cwd)) if cwd else ""
    files = _files_touched(session_jsonl)
    written_at = datetime.now().astimezone().isoformat(timespec="seconds")

    lines: list[str] = ["# Handoff (slim)", ""]
    lines.append("Compound-loop gates blocked LLM evaluation; this is a deterministic snapshot.")
    lines.append("")
    lines.append(f"- Written at: {written_at}")
    if branch:
        lines.append(f"- Branch: `{branch}`")
    lines.append("")
    lines.append("## Last user prompt")
    lines.append("")
    lines.append(last_prompt)
    lines.append("")
    if files:
        lines.append("## Files touched")
        lines.append("")
        for fp in files:
            lines.append(f"- `{fp}`")
        lines.append("")

    memory_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(memory_dir / "handoff.md", "\n".join(lines))
    return True


def count_user_chars(session_jsonl: Path) -> int:
    """Total characters in user text messages. Used as a signal of session weight."""
    total = 0
    try:
        with open(session_jsonl) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if d.get("type") != "user":
                    continue
                msg = d.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, str):
                    total += len(content.strip())
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            total += len(block.get("text", "").strip())
    except OSError:
        return 0
    return total


def extract_messages(session_jsonl: Path, tail: int = 20) -> tuple[str, int]:
    """Extract messages from a session JSONL into a markdown summary.

    Returns (formatted_text, total_message_count). Only the last `tail`
    messages are included in the formatted text to keep the prompt bounded.
    """
    messages: list[str] = []
    try:
        with open(session_jsonl) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                msg_type = d.get("type")
                if msg_type not in ("user", "assistant"):
                    continue
                msg = d.get("message", {})
                content = msg.get("content", "")
                texts: list[str] = []
                if isinstance(content, str) and content.strip():
                    texts.append(content.strip())
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            t = block.get("text", "").strip()
                            if t:
                                texts.append(t)
                if texts:
                    role = "User" if msg_type == "user" else "Assistant"
                    messages.append(f"## {role}\n\n{chr(10).join(texts)}")
    except OSError:
        return "", 0
    return "\n\n".join(messages[-tail:]), len(messages)


def parse_task(task_file: Path) -> dict[str, str]:
    """Parse a `key=value` task file dropped by the Stop hook."""
    result: dict[str, str] = {}
    for line in task_file.read_text().splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def create_task(
    queue_dir: Path,
    cwd: Path,
    session_jsonl: Path,
    session_id: str,
    memory_dir: Path,
) -> Path:
    """Drop a task file in the queue. Returns its path."""
    queue_dir.mkdir(parents=True, exist_ok=True)
    short_id = session_id[:8]
    task_file = queue_dir / f"{int(time.time())}-{short_id}.task"
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    task_file.write_text(
        f"cwd={cwd}\n"
        f"session_jsonl={session_jsonl}\n"
        f"session_id={session_id}\n"
        f"memory_dir={memory_dir}\n"
        f"timestamp={timestamp}\n"
    )
    return task_file


def is_debounced(queue_dir: Path, session_id: str, window_seconds: int) -> bool:
    """True if a task for this session was queued within `window_seconds`."""
    short_id = session_id[:8]
    now = time.time()
    for f in queue_dir.glob(f"*-{short_id}.task"):
        try:
            age = now - f.stat().st_mtime
        except OSError:
            continue
        if age < window_seconds:
            return True
    return False


def last_processed_mtime(queue_dir: Path, session_id: str) -> float | None:
    """Return the mtime of the most recent processed task for `session_id`.

    None if the session has never been processed. Used to decide whether a
    new Stop event should re-run the evaluator: if the session JSONL has
    grown past a threshold since this timestamp, it's worth re-processing.
    """
    done_dir = queue_dir / "done"
    if not done_dir.is_dir():
        return None
    short_id = session_id[:8]
    best: float | None = None
    for f in done_dir.glob(f"*-{short_id}.task"):
        try:
            m = f.stat().st_mtime
        except OSError:
            continue
        if best is None or m > best:
            best = m
    return best


def should_reprocess(
    session_jsonl: Path, last_processed: float | None, min_growth_seconds: int
) -> bool:
    """True if the session is eligible for re-evaluation.

    Policy: process once if never seen; re-process only after the session's
    JSONL has grown by at least `min_growth_seconds` of wall time since the
    previous successful processing. Bounds LLM cost on long sessions.
    """
    if last_processed is None:
        return True
    try:
        session_mtime = session_jsonl.stat().st_mtime
    except OSError:
        return False
    return session_mtime - last_processed >= min_growth_seconds


def should_queue_task(
    *,
    queue_dir: Path,
    session_jsonl: Path,
    session_id: str,
    debounce_seconds: int,
    min_growth_seconds: int,
    force: bool,
) -> bool:
    """Combine debounce + growth gates, with an override for session-end paths.

    When `force=True` (e.g. the SessionEnd hook fired, or a user invoked
    `lh knowledge handoff-now`), bypass both gates: the caller is asserting
    that the session is closing and the handoff must reflect its final state.
    """
    if force:
        return True
    if is_debounced(queue_dir, session_id, debounce_seconds):
        return False
    return should_reprocess(
        session_jsonl, last_processed_mtime(queue_dir, session_id), min_growth_seconds
    )


def collect_existing_learnings(learnings_dir: Path, limit: int = 50) -> str:
    """Collect titles of recent learnings for semantic deduplication."""
    if not learnings_dir.is_dir():
        return ""
    titles: list[str] = []
    for md_file in sorted(learnings_dir.rglob("*.md"), reverse=True):
        if md_file.name.startswith("_review-"):
            continue
        try:
            for line in md_file.read_text().splitlines():
                if line.startswith("title:"):
                    title = line.split(":", 1)[1].strip().strip('"')
                    titles.append(title)
                    break
        except OSError:
            continue
        if len(titles) >= limit:
            break
    return "\n".join(f"- {t}" for t in titles)


def _collect_jsonl_summaries(jsonl_file: Path, limit: int = 10) -> str:
    if not jsonl_file.is_file():
        return ""
    summaries: list[str] = []
    try:
        lines = jsonl_file.read_text().splitlines()
    except OSError:
        return ""
    for line in lines[-limit:]:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        summary = d.get("summary", "")
        if summary:
            summaries.append(f"- {summary}")
    return "\n".join(summaries)


def collect_existing_decisions(memory_dir: Path, limit: int = 10) -> str:
    return _collect_jsonl_summaries(memory_dir / "decisions.jsonl", limit)


def collect_existing_failures(memory_dir: Path, limit: int = 10) -> str:
    return _collect_jsonl_summaries(memory_dir / "failures.jsonl", limit)


def build_prompt(
    project_name: str,
    cwd: str,
    session_id: str,
    timestamp: str,
    existing_decisions: str,
    existing_failures: str,
    existing_learnings: str,
    summary: str,
    captured_insights: list[Insight] | None = None,
) -> str:
    """Build the headless-Claude prompt. Ported verbatim from the bash worker
    to preserve the calibration of the evaluator — reword with care."""
    insights_section = ""
    if captured_insights:
        titles = "\n".join(f"- {_first_line(i.body)}" for i in captured_insights)
        insights_section = (
            "\n## Insights already captured verbatim from this session "
            "(DO NOT re-emit as learnings):\n"
            f"{titles}\n"
        )
    return f"""You are evaluating a Claude Code session for learnings. Analyze the conversation and output ONLY valid JSON.

Project: {project_name}
CWD: {cwd}
Session: {session_id}
Timestamp: {timestamp}

## Recent decisions already recorded (avoid duplicates):
{existing_decisions}

## Recent failures already recorded (avoid duplicates):
{existing_failures}

## Existing learnings already recorded (DO NOT repeat these or semantic equivalents):
{existing_learnings}
{insights_section}
## Session conversation:
{summary}

## Output format

Return ONLY this JSON structure (no markdown fences, no explanation):
{{
  "decisions": [
    {{"summary": "...", "context": "...", "alternatives": ["..."], "rationale": "...", "tags": ["..."]}}
  ],
  "failures": [
    {{"summary": "...", "root_cause": "...", "resolution": "...", "prevention": "...", "tags": ["..."]}}
  ],
  "learnings": [
    {{"title": "...", "learning": "1-2 sentences", "context": "...", "scope": "universal|backend|infra|consulting", "tags": ["..."]}}
  ],
  "handoff": ["concrete pending item for next session"],
  "claude_md_proposals": [
    {{"rule": "one-line workflow rule worth adding to this project's CLAUDE.md", "rationale": "why this rule belongs in CLAUDE.md specifically"}}
  ],
  "grade": {{
    "quality": "excellent|good|acceptable|poor",
    "issues": ["incomplete|hallucination|tool_misuse|missed_context|wrong_approach|inefficient|none"],
    "reasoning": "1-2 sentences on why this grade",
    "confidence": 0.0
  }}
}}

Rules:
- decisions: architectural or design decisions made. Skip if already in recent decisions above.
- failures: preventable errors. Skip if already in recent failures above. Include root cause and prevention.
- learnings: ONLY transferable knowledge useful outside this project. Universal patterns, reusable insights. Project-specific stuff goes in decisions.
- claude_md_proposals: workflow rules or conventions that emerged this session and would belong as a bullet in *this project's* CLAUDE.md. Different from learnings (cross-project) and decisions (one-off). Only include if the rule is concrete, durable, and specific to how to work in this repo. Empty list `[]` if nothing qualifies — this is the common case.
- CRITICAL: Check ALL existing lists above. If a decision, failure, or learning already exists that covers the same concept (even with different wording), do NOT generate a new one. Only add genuinely new insights.
- handoff: concrete, actionable items left pending for the next session. NOT summaries of what was done. Only what remains to be done. If everything was resolved or it was just a Q&A, return [].
- grade: rate the assistant's overall performance against the user's intent. quality is one of excellent|good|acceptable|poor. issues come from this fixed taxonomy: incomplete (stopped before resolving), hallucination (invented APIs/files/tools), tool_misuse (wrong tool/args/repeated failures), missed_context (ignored a stated constraint), wrong_approach (solved a different problem), inefficient (right answer, avoidable cost), none (no issues observed). Use ["none"] when quality is excellent or good. confidence is 0.0-1.0. reasoning must reference concrete evidence from the transcript.
- Empty session or just status checks? Return {{"decisions": [], "failures": [], "learnings": [], "handoff": [], "claude_md_proposals": [], "grade": {{"quality": "good", "issues": ["none"], "reasoning": "trivial session", "confidence": 0.9}}}}
- Output ONLY the JSON object."""


def strip_markdown_fences(text: str) -> str:
    """Strip a leading/trailing ``` fence from an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def parse_response(raw_output: str) -> dict | None:
    """Strip fences and parse the JSON payload. Returns None on failure.

    Handles three common shapes from `claude -p`:
      1. Bare JSON object
      2. ```json ... ``` fenced block at the start
      3. Prose preamble followed by a JSON object somewhere in the text
    """
    cleaned = strip_markdown_fences(raw_output)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fallback: find the first balanced JSON object in the text.
    start = cleaned.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def invoke_llm(prompt: str, backend: LLMBackend, model: str, timeout: int) -> str | None:
    """Run a single-turn completion via the backend (ADR-033).

    Returns the response text, or None on failure or empty output — the
    historical `invoke_claude` contract, now provider-agnostic.
    """
    try:
        output = backend.complete(prompt, model, timeout)
    except LLMBackendError:
        return None
    return output if output else None


def _atomic_write(path: Path, content: str) -> None:
    """Atomic write via tempfile in the same dir + os.replace.

    iCloud/Dropbox observe a single rename event instead of an open-write-close
    window. Required whenever LEARNINGS_DIR points into a cloud-synced directory.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)


def _slugify(title: str, max_len: int = 50) -> str:
    slug = re.sub(r"[^a-z0-9\-_ ]", "", title.lower()).strip().replace(" ", "-")
    return slug[:max_len] or "untitled"


def persist_results(
    data: dict,
    memory_dir: Path,
    learnings_dir: Path,
    project_name: str,
    timestamp: str,
    *,
    session_id: str = "",
    session_jsonl: Path | None = None,
) -> list[str]:
    """Persist decisions/failures/learnings/handoff. Returns a list of summaries
    of what was written, suitable for logging. Atomic writes everywhere."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    wrote: list[str] = []

    for d in data.get("decisions", []):
        entry = {
            "ts": timestamp,
            "type": "decision",
            "summary": d.get("summary", ""),
            "context": d.get("context", ""),
            "alternatives": d.get("alternatives", []),
            "rationale": d.get("rationale", ""),
            "project": project_name,
            "tags": d.get("tags", []),
        }
        with open(memory_dir / "decisions.jsonl", "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        wrote.append(f"decision: {d.get('summary', '')[:60]}")

    for fe in data.get("failures", []):
        entry = {
            "ts": timestamp,
            "type": "failure",
            "summary": fe.get("summary", ""),
            "root_cause": fe.get("root_cause", ""),
            "resolution": fe.get("resolution", ""),
            "prevention": fe.get("prevention", ""),
            "project": project_name,
            "tags": fe.get("tags", []),
        }
        with open(memory_dir / "failures.jsonl", "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        wrote.append(f"failure: {fe.get('summary', '')[:60]}")

    date_str = timestamp[:10] if len(timestamp) >= 10 else "unknown"
    year_month = date_str[:7]
    learnings_subdir = learnings_dir / year_month

    for learning in data.get("learnings", []):
        title = learning.get("title", "untitled")
        filepath = learnings_subdir / f"{date_str}-{_slugify(title)}.md"
        if filepath.exists():
            continue
        tags_json = json.dumps(learning.get("tags", []))
        scope = learning.get("scope", "universal")
        content = f"""---
title: "{title}"
origin: {project_name}
origin_session: {date_str}
tags: {tags_json}
scope: {scope}
status: active
deprecated_by: null
deprecated_on: null
deprecated_reason: null
---

## Learning

{learning.get("learning", "")}

## Context

{learning.get("context", "")}
"""
        _atomic_write(filepath, content)
        wrote.append(f"learning: {title[:60]}")

    grade = data.get("grade")
    if isinstance(grade, dict) and grade.get("quality"):
        grade_entry = {
            "ts": timestamp,
            "type": "grade",
            "session_id": session_id,
            "project": project_name,
            "quality": grade.get("quality", ""),
            "issues": grade.get("issues", []),
            "reasoning": grade.get("reasoning", ""),
            "confidence": grade.get("confidence", 0.0),
        }
        with open(memory_dir / "grades.jsonl", "a") as f:
            f.write(json.dumps(grade_entry, ensure_ascii=False) + "\n")
        wrote.append(f"grade: {grade.get('quality', '')}")

    proposals = [
        p for p in data.get("claude_md_proposals", []) if isinstance(p, dict) and p.get("rule")
    ]
    if proposals:
        proposal_file = memory_dir / "claude-md.proposal.md"
        block_lines = [f"## {timestamp}\n"]
        for p in proposals:
            block_lines.append(f"- **Rule:** {p.get('rule', '')}")
            rationale = p.get("rationale", "")
            if rationale:
                block_lines.append(f"  - **Rationale:** {rationale}")
        block_lines.append("")
        block = "\n".join(block_lines)
        if proposal_file.exists():
            existing = proposal_file.read_text()
            _atomic_write(proposal_file, existing + "\n" + block)
        else:
            header = (
                "<!-- claude-md proposals (append-only). "
                "Review and merge into CLAUDE.md or discard. -->\n\n"
            )
            _atomic_write(proposal_file, header + block)
        wrote.append(f"claude_md_proposals: {len(proposals)}")

    handoff_file = memory_dir / "handoff.md"
    handoff_items = data.get("handoff", [])
    if handoff_items:
        lines = "\n".join(f"- {item}" for item in handoff_items)
        body = f"Pendiente para próxima sesión:\n{lines}\n"
        if session_id and session_jsonl is not None:
            try:
                source_mtime = session_jsonl.stat().st_mtime
            except OSError:
                source_mtime = 0.0
            frontmatter = (
                "---\n"
                f"session_id: {session_id}\n"
                f"written_at: {timestamp}\n"
                f"source_mtime: {source_mtime:.0f}\n"
                "---\n"
            )
            body = frontmatter + body
        _atomic_write(handoff_file, body)
        wrote.append(f"handoff: {len(handoff_items)} items")
    elif handoff_file.exists():
        handoff_file.unlink()

    return wrote


_PRJ_NAME_PREFIXES = ("lazy-", "flex-", "mngt-", "prj-")


def _name_variants(name: str) -> set[str]:
    """Return alphanumeric-only lowercased variants of `name`, with and without
    common project prefixes. A match between two names is then a non-empty
    intersection of their variant sets."""
    n = name.lower().replace("_", "-").replace(" ", "-")
    variants = {re.sub(r"[^a-z0-9]", "", n)}
    for prefix in _PRJ_NAME_PREFIXES:
        if n.startswith(prefix):
            variants.add(re.sub(r"[^a-z0-9]", "", n[len(prefix) :]))
    variants.discard("")
    return variants


def resolve_prj_md(project_name: str, lazymind_dir: Path) -> Path | None:
    """Find LazyMind/1-Projects/PRJ-<X>/PRJ-<X>.md matching project_name.

    Comparison normalises both sides to alphanumeric-only lowercase and
    optionally strips common prefixes (lazy-, flex-, mngt-, prj-). Returns
    None when the directory is missing or no candidate matches.
    """
    projects_dir = lazymind_dir / "1-Projects"
    if not projects_dir.is_dir():
        return None
    target_variants = _name_variants(project_name)
    if not target_variants:
        return None
    for candidate in projects_dir.glob("PRJ-*/PRJ-*.md"):
        stem = candidate.stem
        if not stem.startswith("PRJ-"):
            continue
        if target_variants & _name_variants(stem[4:]):
            return candidate
    return None


def _grade_warrants_backlog_entry(grade: dict) -> bool:
    quality = grade.get("quality", "")
    issues = [i for i in grade.get("issues", []) if i and i != "none"]
    if quality == "poor":
        return True
    if quality == "acceptable" and issues:
        return True
    return False


_ALTA_HEADER = "### Pendiente — Alta prioridad"


def append_grade_to_prj_backlog(
    prj_md: Path,
    grade: dict,
    date_str: str,
    session_id: str,
) -> bool:
    """Append a backlog item under '### Pendiente — Alta prioridad' if the grade
    warrants escalation. Returns True if an entry was written, False otherwise.

    Best-effort: returns False (without raising) when the section is missing or
    the file cannot be parsed."""
    if not _grade_warrants_backlog_entry(grade):
        return False
    try:
        text = prj_md.read_text()
    except OSError:
        return False
    if _ALTA_HEADER not in text:
        return False
    issues = [i for i in grade.get("issues", []) if i and i != "none"]
    issues_str = ", ".join(issues) if issues else "none"
    short_id = session_id[:8] if session_id else "unknown"
    reasoning = grade.get("reasoning", "").strip() or "no reasoning given"
    item = (
        f"- [ ] **Session quality regression — {reasoning}** "
        f"(graded {date_str}, session {short_id}, issues: {issues_str})\n"
    )
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    inserted = False
    for i, line in enumerate(lines):
        out.append(line)
        if inserted or line.rstrip() != _ALTA_HEADER:
            continue
        # Skip a single blank line after the header, then insert our item
        # before any existing content (so the most recent regression sits on top).
        j = i + 1
        if j < len(lines) and lines[j].strip() == "":
            out.append(lines[j])
            j += 1
        out.append(item)
        # Append the rest verbatim and break the outer loop via slice.
        out.extend(lines[j:])
        inserted = True
        break
    if not inserted:
        return False
    _atomic_write(prj_md, "".join(out))
    return True


class TaskOutcome:
    """Result of processing a single task — pure data for logging and tests."""

    def __init__(self, skipped: str | None = None, wrote: list[str] | None = None) -> None:
        self.skipped = skipped
        self.wrote = wrote or []

    @property
    def was_processed(self) -> bool:
        return self.skipped is None


def process_task(
    task_file: Path,
    cfg: CompoundLoopConfig,
    learnings_dir: Path,
    backend: LLMBackend | None = None,
) -> TaskOutcome:
    """Process one queued task. `backend` defaults to ClaudeBackend (ADR-033)."""
    if backend is None:
        backend = ClaudeBackend()
    meta = parse_task(task_file)
    session_jsonl = Path(meta.get("session_jsonl", ""))
    session_id = meta.get("session_id", "")
    cwd = meta.get("cwd", "")
    memory_dir = Path(meta.get("memory_dir", ""))
    timestamp = meta.get("timestamp", "")

    if not session_jsonl.is_file():
        return TaskOutcome(skipped=f"session JSONL not found: {session_jsonl}")

    if not is_interactive_session(session_jsonl):
        return TaskOutcome(skipped=f"non-interactive: {session_id[:8]}")

    cursor = _read_insight_cursor(memory_dir, session_id)
    insights = extract_insights(session_jsonl, since_index=cursor + 1)
    persisted_insights = persist_insights(memory_dir, insights) if insights else []
    if insights:
        last_idx = max(i.message_index for i in insights)
        _write_insight_cursor(memory_dir, session_id, last_idx)
    insight_bypass = bool(insights)

    user_chars = count_user_chars(session_jsonl)
    if user_chars < cfg.min_user_chars and not insight_bypass:
        if cfg.slim_handoff_enabled:
            write_slim_handoff(session_jsonl, memory_dir, cwd)
        return TaskOutcome(skipped=f"{user_chars} user chars (min {cfg.min_user_chars})")

    summary, msg_count = extract_messages(session_jsonl)
    if (not summary or msg_count < cfg.min_messages) and not insight_bypass:
        if cfg.slim_handoff_enabled:
            write_slim_handoff(session_jsonl, memory_dir, cwd)
        return TaskOutcome(skipped=f"{msg_count} messages (min {cfg.min_messages})")

    existing_decisions = collect_existing_decisions(memory_dir)
    existing_failures = collect_existing_failures(memory_dir)
    existing_learnings = collect_existing_learnings(learnings_dir)

    project_name = os.path.basename(cwd)
    prompt = build_prompt(
        project_name,
        cwd,
        session_id,
        timestamp,
        existing_decisions,
        existing_failures,
        existing_learnings,
        summary,
    )

    raw_output = invoke_llm(prompt, backend, cfg.model, cfg.timeout_seconds)
    if not raw_output:
        return TaskOutcome(skipped=f"{backend.name} returned empty for {session_id[:8]}")

    data = parse_response(raw_output)
    if data is None:
        snippet = raw_output[:200].replace("\n", " ")
        return TaskOutcome(skipped=f"JSON parse failed for {session_id[:8]} — raw: {snippet}")

    wrote = persist_results(
        data,
        memory_dir,
        learnings_dir,
        project_name,
        timestamp,
        session_id=session_id,
        session_jsonl=session_jsonl,
    )

    if persisted_insights:
        wrote.append(f"insights: {len(persisted_insights)}")

    grade = data.get("grade")
    if cfg.grading_enabled and isinstance(grade, dict) and cfg.lazymind_dir:
        prj_md = resolve_prj_md(project_name, Path(cfg.lazymind_dir))
        if prj_md is not None:
            date_str = timestamp[:10] if len(timestamp) >= 10 else "unknown"
            if append_grade_to_prj_backlog(prj_md, grade, date_str, session_id):
                wrote.append(f"backlog: {prj_md.name}")

    return TaskOutcome(wrote=wrote)


def move_to_done(queue_dir: Path, task_file: Path) -> None:
    done_dir = queue_dir / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(task_file), str(done_dir / task_file.name))
    except OSError:
        pass
