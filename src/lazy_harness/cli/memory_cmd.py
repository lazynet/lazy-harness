"""lh memory — diagnostic commands for the memory stack (ADR-030 G7)."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import click

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file, expand_path
from lazy_harness.knowledge.compound_loop import invoke_llm as _invoke_llm
from lazy_harness.llm import (
    LLMBackend,
    LLMBackendError,
    LLMBackendNotFoundError,
    get_backend,
)
from lazy_harness.llm.claude import ClaudeBackend


def _resolve_backend_and_model() -> tuple[LLMBackend, str]:
    """Resolve [compound_loop].backend and .model from config.toml (ADR-033).

    Missing or unloadable config falls back to ClaudeBackend and its default
    model — the same bootstrap default as the compound-loop worker. With a
    loadable config the model is `[compound_loop].model`, mirroring how the
    worker passes `cfg.model` to `process_task`.
    """
    cf = config_file()
    if not cf.is_file():
        backend: LLMBackend = ClaudeBackend()
        return backend, backend.default_model()
    try:
        cfg = load_config(cf)
    except ConfigError:
        backend = ClaudeBackend()
        return backend, backend.default_model()
    try:
        return get_backend(cfg.compound_loop), cfg.compound_loop.model
    except (LLMBackendError, LLMBackendNotFoundError) as e:
        raise click.ClickException(str(e)) from e


def enumerate_profile_projects(profile_dir: Path) -> dict[str, dict]:
    """List per-project memory artifacts under `<profile_dir>/projects/`.

    Returns a mapping of project_key → {memory_md_lines, memory_md_sha,
    has_decisions, has_handoff}. Skips any project_key that lacks a
    `MEMORY.md` (it has no curated content yet).
    """
    projects_dir = profile_dir / "projects"
    if not projects_dir.is_dir():
        return {}
    out: dict[str, dict] = {}
    for entry in projects_dir.iterdir():
        if not entry.is_dir():
            continue
        memory_dir = entry / "memory"
        memory_md = memory_dir / "MEMORY.md"
        if not memory_md.is_file():
            continue
        try:
            content_bytes = memory_md.read_bytes()
        except OSError:
            continue
        text = content_bytes.decode("utf-8", errors="replace")
        out[entry.name] = {
            "memory_md_lines": text.count("\n") + (0 if text.endswith("\n") else 1),
            "memory_md_sha": hashlib.sha256(content_bytes).hexdigest()[:12],
            "has_decisions": (memory_dir / "decisions.jsonl").is_file(),
            "has_handoff": (memory_dir / "handoff.md").is_file(),
        }
    return out


def find_cross_profile_divergences(
    profile_data: dict[str, dict[str, dict]],
) -> list[dict]:
    """Find project keys that exist in 2+ profiles with divergent MEMORY.md.

    Returns a list of {project_key, profiles: dict[profile_name, data]} for
    each shared key whose `memory_md_sha` differs across the profiles that
    own it.
    """
    if len(profile_data) < 2:
        return []
    all_keys: set[str] = set()
    for proj in profile_data.values():
        all_keys.update(proj.keys())
    out: list[dict] = []
    for key in sorted(all_keys):
        owners = {name: proj[key] for name, proj in profile_data.items() if key in proj}
        if len(owners) < 2:
            continue
        shas = {entry["memory_md_sha"] for entry in owners.values()}
        if len(shas) > 1:
            out.append({"project_key": key, "profiles": owners})
    return out


@click.group("memory")
def memory() -> None:
    """Diagnostic commands for the memory stack."""


@memory.command("cross-profile-check")
def cross_profile_check() -> None:
    """List per-profile memory artifacts and flag cross-profile divergences."""
    from lazy_harness.core.config import ConfigError, load_config

    cf = config_file()
    if not cf.is_file():
        click.echo(f"No config at {cf} — nothing to check.")
        return
    try:
        cfg = load_config(cf)
    except ConfigError as exc:
        click.echo(f"Config invalid: {exc}", err=True)
        raise SystemExit(1) from exc

    profile_data: dict[str, dict[str, dict]] = {}
    for name, entry in cfg.profiles.items.items():
        config_dir = expand_path(entry.config_dir)
        profile_data[name] = enumerate_profile_projects(config_dir)
        click.echo(f"[{name}] {config_dir} — {len(profile_data[name])} project(s) with MEMORY.md")
        for key in sorted(profile_data[name].keys()):
            stats = profile_data[name][key]
            extras = []
            if stats["has_decisions"]:
                extras.append("decisions")
            if stats["has_handoff"]:
                extras.append("handoff")
            tail = f" [{', '.join(extras)}]" if extras else ""
            click.echo(
                f"  · {key} — {stats['memory_md_lines']} lines, sha {stats['memory_md_sha']}{tail}"
            )

    divergences = find_cross_profile_divergences(profile_data)
    if divergences:
        click.echo()
        click.echo(f"Cross-profile divergences ({len(divergences)}):")
        for d in divergences:
            owners = ", ".join(
                f"{name}=sha:{entry['memory_md_sha']}/lines:{entry['memory_md_lines']}"
                for name, entry in d["profiles"].items()
            )
            click.echo(f"  ⚠ {d['project_key']} → {owners}")
    else:
        click.echo()
        click.echo("No cross-profile divergences detected.")


def _read_jsonl_tail(path: Path, last: int) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    return [line for line in lines[-last:] if line.strip()]


def _build_consolidate_prompt(decisions: list[str], failures: list[str]) -> str:
    sections: list[str] = [
        "You are reviewing append-only episodic logs from a coding agent's session.",
        "Identify recurring patterns and propose additions to the project's curated",
        "MEMORY.md (max 200 lines, distilled rules and conventions). Output only the",
        "additions as markdown bullets — no preamble. Each addition must include the",
        "source decisions/failures that motivate it. Skip anything that is already a",
        "one-off or session-specific.",
    ]
    if decisions:
        sections.append("\n## decisions.jsonl entries")
        sections.extend(decisions)
    if failures:
        sections.append("\n## failures.jsonl entries")
        sections.extend(failures)
    return "\n".join(sections)


@memory.command("consolidate")
@click.option(
    "--memory-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Memory directory to read from. Defaults to <cwd>/memory.",
)
@click.option(
    "--last",
    type=int,
    default=50,
    show_default=True,
    help="Tail this many entries from each JSONL.",
)
@click.option(
    "--model",
    default=None,
    help="Headless model for the proposal. Defaults to [compound_loop].model.",
)
@click.option(
    "--timeout",
    type=int,
    default=120,
    show_default=True,
    help="LLM invocation timeout in seconds.",
)
def consolidate(memory_dir: Path | None, last: int, model: str | None, timeout: int) -> None:
    """Propose MEMORY.md additions from recent decisions/failures (read-only)."""
    target = memory_dir or (Path.cwd() / "memory")
    decisions = _read_jsonl_tail(target / "decisions.jsonl", last)
    failures = _read_jsonl_tail(target / "failures.jsonl", last)
    if not decisions and not failures:
        click.echo(
            f"No entries in decisions.jsonl/failures.jsonl — nothing to consolidate at {target}."
        )
        return

    prompt = _build_consolidate_prompt(decisions, failures)
    backend, default_model = _resolve_backend_and_model()
    result = _invoke_llm(prompt, backend, model or default_model, timeout)
    if not result:
        click.echo("The LLM backend returned empty output. Try again or increase --timeout.")
        return
    click.echo(result)
    click.echo(
        "\n# Above is a proposal — review before pasting into MEMORY.md.\n"
        "# Use LH_MEMORY_SIZE_BYPASS=1 if your edit transiently exceeds 200 lines."
    )


# --- claude-md proposals lifecycle (Phase 3c) ---

_RULE_PREFIX = "- **Rule:**"
_RATIONALE_PREFIX = "- **Rationale:**"


@dataclass(frozen=True)
class PendingProposal:
    """One `- **Rule:**` bullet from claude-md.proposal.md, with line spans."""

    timestamp: str
    rule: str
    rationale: str
    start_line: int
    end_line: int  # exclusive
    header_line: int  # line index of the owning `## <timestamp>` header, -1 if none


def parse_proposals(text: str) -> list[PendingProposal]:
    """Parse pending proposal bullets out of claude-md.proposal.md content.

    Tolerates the archived-comments-only file state: HTML comments and
    anything outside `- **Rule:**` bullets are ignored.
    """
    lines = text.splitlines()
    proposals: list[PendingProposal] = []
    in_comment = False
    header_ts = ""
    header_line = -1
    current: dict[str, object] | None = None

    def close(end: int) -> None:
        nonlocal current
        if current is None:
            return
        start = int(current["start"])
        while end - 1 > start and not lines[end - 1].strip():
            end -= 1
        proposals.append(
            PendingProposal(
                timestamp=str(current["timestamp"]),
                rule=str(current["rule"]),
                rationale=str(current["rationale"]),
                start_line=start,
                end_line=end,
                header_line=int(current["header_line"]),
            )
        )
        current = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            close(i)
            if "-->" not in stripped:
                in_comment = True
            continue
        if stripped.startswith("## "):
            close(i)
            header_ts = stripped[3:].strip()
            header_line = i
            continue
        if stripped.startswith(_RULE_PREFIX) and not line.startswith(" "):
            close(i)
            current = {
                "timestamp": header_ts,
                "rule": stripped[len(_RULE_PREFIX) :].strip(),
                "rationale": "",
                "start": i,
                "header_line": header_line,
            }
            continue
        if current is not None and stripped.startswith(_RATIONALE_PREFIX):
            current["rationale"] = stripped[len(_RATIONALE_PREFIX) :].strip()
    close(len(lines))
    return proposals


def _remove_proposal(text: str, proposals: list[PendingProposal], index: int) -> str:
    """Return `text` without proposal `index` (0-based), dropping its section
    header when no sibling rule remains under it."""
    target = proposals[index]
    drop = set(range(target.start_line, target.end_line))
    header_shared = any(
        p.header_line == target.header_line for i, p in enumerate(proposals) if i != index
    )
    lines = text.splitlines()
    if target.header_line >= 0 and not header_shared:
        drop.add(target.header_line)
        j = target.header_line + 1
        while j < len(lines) and not lines[j].strip():
            drop.add(j)
            j += 1
    kept = [line for i, line in enumerate(lines) if i not in drop]
    out = "\n".join(kept).rstrip("\n")
    return out + "\n" if out else ""


def _atomic_write(path: Path, content: str) -> None:
    """Atomic write via tempfile + os.replace (mirrors knowledge.compound_loop)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)


def _append_block(path: Path, header_comment: str, block: str) -> None:
    if path.exists():
        existing = path.read_text()
        _atomic_write(path, existing.rstrip("\n") + "\n\n" + block)
    else:
        _atomic_write(path, header_comment + block)


def _format_entry_block(proposal: PendingProposal, status_lines: list[str]) -> str:
    lines = [f"## {proposal.timestamp}"]
    lines.extend(status_lines)
    lines.append("")
    lines.append(f"{_RULE_PREFIX} {proposal.rule}")
    if proposal.rationale:
        lines.append(f"  {_RATIONALE_PREFIX} {proposal.rationale}")
    lines.append("")
    return "\n".join(lines)


def _project_memory_dir() -> Path:
    """Resolve `<agent_dir>/<sessions>/<encoded cwd>/memory` (ADR-032 pattern)."""
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.core.paths import agent_runtime_dir

    agent_type = "claude-code"
    cf = config_file()
    if cf.is_file():
        try:
            agent_type = load_config(cf).agent.type
        except ConfigError:
            pass
    agent = get_agent(agent_type)
    agent_dir = agent_runtime_dir(agent)
    subdirs = agent.session_dirs()
    encoded = "-" + str(Path.cwd()).replace("/", "-").lstrip("-")
    return agent_dir / (subdirs.get("sessions") or "projects") / encoded / "memory"


def _load_pending(memory_dir: Path | None) -> tuple[Path, str, list[PendingProposal]]:
    target = memory_dir or _project_memory_dir()
    pending_file = target / "claude-md.proposal.md"
    text = pending_file.read_text() if pending_file.is_file() else ""
    return pending_file, text, parse_proposals(text)


def _get_proposal_or_fail(proposals: list[PendingProposal], index: int) -> PendingProposal:
    if index < 1 or index > len(proposals):
        raise click.ClickException(
            f"No proposal #{index} — {len(proposals)} pending. "
            "Run `lh memory proposals list`."
        )
    return proposals[index - 1]


_MEMORY_DIR_OPTION = click.option(
    "--memory-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Project memory directory. Defaults to the agent runtime dir for this cwd.",
)


@memory.group("proposals")
def proposals() -> None:
    """Review compound-loop claude-md proposals: list, accept, reject."""


@proposals.command("list")
@_MEMORY_DIR_OPTION
def proposals_list(memory_dir: Path | None) -> None:
    """List pending claude-md proposals."""
    pending_file, _, pending = _load_pending(memory_dir)
    if not pending:
        click.echo(f"No pending claude-md proposals at {pending_file}.")
        return
    click.echo(f"Pending claude-md proposals ({pending_file}):")
    for i, p in enumerate(pending, start=1):
        excerpt = p.rule if len(p.rule) <= 72 else p.rule[:69] + "..."
        click.echo(f"  {i:>3}  {p.timestamp[:10] or '????-??-??'}  {excerpt}")
    click.echo("\nAccept: lh memory proposals accept <N> — reject: "
               "lh memory proposals reject <N> --reason \"...\"")


@proposals.command("accept")
@click.argument("index", type=int)
@_MEMORY_DIR_OPTION
def proposals_accept(index: int, memory_dir: Path | None) -> None:
    """Accept proposal N: archive it and print the rule for manual merge."""
    pending_file, text, pending = _load_pending(memory_dir)
    target = _get_proposal_or_fail(pending, index)

    block = _format_entry_block(target, [f"accepted: {date.today().isoformat()}"])
    _append_block(
        pending_file.with_name("claude-md.accepted.md"),
        "<!-- accepted claude-md proposals (append-only). -->\n\n",
        block,
    )
    _atomic_write(pending_file, _remove_proposal(text, pending, index - 1))

    click.echo(f"Accepted proposal #{index}:\n")
    click.echo(f"  {target.rule}")
    if target.rationale:
        click.echo(f"  Rationale: {target.rationale}")
    click.echo(
        "\nThis was NOT applied automatically — "
        "add it to MEMORY.md or the project CLAUDE.md yourself."
    )


@proposals.command("reject")
@click.argument("index", type=int)
@click.option("--reason", required=True, help="Why this rule is rejected (immunity registry).")
@_MEMORY_DIR_OPTION
def proposals_reject(index: int, reason: str, memory_dir: Path | None) -> None:
    """Reject proposal N: move it to the rejected registry with a reason."""
    pending_file, text, pending = _load_pending(memory_dir)
    target = _get_proposal_or_fail(pending, index)

    block = _format_entry_block(
        target,
        [f"rejected: {date.today().isoformat()}", f"reason: {reason}"],
    )
    _append_block(
        pending_file.with_name("claude-md.rejected.md"),
        "<!-- rejected claude-md proposals (append-only immunity registry). -->\n\n",
        block,
    )
    _atomic_write(pending_file, _remove_proposal(text, pending, index - 1))
    click.echo(f"Rejected proposal #{index}: {target.rule}")
    click.echo("Recorded in claude-md.rejected.md — the grader will be told not to re-propose it.")
