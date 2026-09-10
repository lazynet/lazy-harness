"""lh memory — diagnostic commands for the memory stack (ADR-030 G7)."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import click

from lazy_harness.core.config import Config, ConfigError, load_config
from lazy_harness.core.paths import config_file
from lazy_harness.core.proposals import (
    _RATIONALE_PREFIX,
    _RULE_PREFIX,
    PendingProposal,
    _remove_proposal,
    parse_proposals,
)
from lazy_harness.llm.invoke import run_inference


def _load_config_for_consolidate() -> Config:
    """Load config.toml, defaulting to an empty Config on missing/unloadable.

    A default `Config()` resolves the `distill` role through the deprecated
    `[compound_loop]` bridge (`resolve_role`), which lands on `ClaudeBackend`
    and its default model — the same bootstrap default as the compound-loop
    worker.
    """
    cf = config_file()
    if not cf.is_file():
        return Config()
    try:
        return load_config(cf)
    except ConfigError:
        return Config()


@click.group("memory")
def memory() -> None:
    """Diagnostic commands for the memory stack."""


@memory.command("legacy-check")
def legacy_check() -> None:
    """Report per-project memory still sitting outside the knowledge store.

    Memory now lives in the store, keyed by project identity. Anything left in
    a profile's `projects/` tree is read by nothing — harmless when the store
    already holds a copy, a quietly lost document when it does not.

    This replaced `cross-profile-check`, which compared profiles for a
    divergence that cannot exist: the knowledge root is global, so two profiles
    have no way to hold different copies of one project's memory.
    """
    from lazy_harness.core.memory_migration import classify_legacy_memory
    from lazy_harness.core.profiles import list_profiles
    from lazy_harness.hooks.builtins._shared import knowledge_root_for

    cf = config_file()
    if not cf.is_file():
        click.echo(f"No config at {cf} — nothing to check.")
        return
    try:
        cfg = load_config(cf)
    except ConfigError as exc:
        click.echo(f"Config invalid: {exc}", err=True)
        raise SystemExit(1) from exc

    profile_dirs = [p.config_dir for p in list_profiles(cfg) if p.exists]
    statuses = classify_legacy_memory(profile_dirs, knowledge_root=knowledge_root_for(cfg))
    if not statuses:
        click.echo("No legacy memory directories.")
        return

    by_status: dict[str, list] = {}
    for s in statuses:
        by_status.setdefault(s.status, []).append(s)

    # Orphaned and diverged first: they are the ones that cost something to
    # leave alone, or to act on. A status missing from this tuple prints
    # nothing at all, so it must list every status the classifier can return.
    for status in ("orphaned", "diverged", "unkeyable", "superseded"):
        found = by_status.get(status, [])
        if not found:
            continue
        click.echo(f"{len(found)} {status}")
        for s in found:
            name = s.checkout.name if s.checkout else s.source.parent.name
            tail = f" — {s.detail}" if s.detail else ""
            click.echo(f"  · {name}{tail}")
        click.echo("")

    if by_status.get("orphaned"):
        click.echo("Orphaned memory is read by nothing. Move it: lh memory migrate")
    if by_status.get("diverged"):
        click.echo(
            "Diverged memory is NOT safe to delete: the store holds a copy, but not "
            "all of it. Diff the named files before removing anything."
        )


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
    cfg = _load_config_for_consolidate()
    result = run_inference(prompt, role="distill", cfg=cfg, timeout=timeout, model=model)
    if not result.success:
        error = result.error.message if result.error else "unknown error"
        click.echo(f"The LLM backend failed ({error}). Try again or increase --timeout.")
        return
    click.echo(result.output)
    click.echo(
        "\n# Above is a proposal — review before pasting into MEMORY.md.\n"
        "# Use LH_MEMORY_SIZE_BYPASS=1 if your edit transiently exceeds 200 lines."
    )


# --- claude-md proposals lifecycle (Phase 3c) ---


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
    """Where this project's distilled memory lives.

    The same resolver the hooks use. Answering this question twice is how one
    side ends up reading a directory the other stopped writing to: the hooks
    moved `MEMORY.md` into the knowledge store, and a CLI still resolving the
    legacy path reports no pending proposals rather than failing.
    """
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.core.paths import agent_runtime_dir
    from lazy_harness.hooks.builtins._shared import knowledge_root_for
    from lazy_harness.hooks.builtins._shared import memory_dir as shared_memory_dir

    cfg = None
    cf = config_file()
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError:
            cfg = None
    agent = get_agent(cfg.agent.type if cfg is not None else "claude-code")
    return shared_memory_dir(
        None,
        agent_dir=agent_runtime_dir(agent),
        sessions_subdir=agent.session_dirs().get("sessions") or "projects",
        cwd=Path.cwd(),
        knowledge_root=knowledge_root_for(cfg),
    )


def _legacy_memory_dir() -> Path:
    """The pre-store location: memory inside the agent's own project directory.

    Resolved through the same helper the store path falls back to, so the two
    answers cannot drift apart.
    """
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.core.paths import agent_runtime_dir
    from lazy_harness.hooks.builtins._shared import resolve_memory_dir

    cfg = None
    cf = config_file()
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError:
            cfg = None
    agent = get_agent(cfg.agent.type if cfg is not None else "claude-code")
    return (
        resolve_memory_dir(
            None,
            agent_dir=agent_runtime_dir(agent),
            sessions_subdir=agent.session_dirs().get("sessions") or "projects",
            cwd=Path.cwd(),
        )
        / "memory"
    )


def _load_pending(memory_dir: Path | None) -> tuple[Path, str, list[PendingProposal]]:
    target = memory_dir or _project_memory_dir()
    pending_file = target / "claude-md.proposal.md"
    text = pending_file.read_text() if pending_file.is_file() else ""
    return pending_file, text, parse_proposals(text)


def _get_proposal_or_fail(proposals: list[PendingProposal], index: int) -> PendingProposal:
    if index < 1 or index > len(proposals):
        raise click.ClickException(
            f"No proposal #{index} — {len(proposals)} pending. Run `lh memory proposals list`."
        )
    return proposals[index - 1]


_MEMORY_DIR_OPTION = click.option(
    "--memory-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Project memory directory. Defaults to the agent runtime dir for this cwd.",
)


def _read_text(path: Path) -> str:
    return path.read_text() if path.is_file() else ""


def _count_rules(path: Path) -> int:
    """Rules, not timestamped blocks.

    One block can carry several rules, and `proposals list` numbers rules — so
    counting blocks here would disagree with the command that drains the queue.
    """
    return sum(1 for line in _read_text(path).splitlines() if line.startswith(_RULE_PREFIX))


def _jsonl_summary(path: Path) -> tuple[int | None, str]:
    """Record count and the most recent date, or (None, "") when absent.

    Rows spell the timestamp two ways — `ts` on everything the compound loop
    writes today, `timestamp` on rows predating the rename — so a reader
    honouring one key silently reports the wrong last-written date. A line that
    does not parse still counts as a record: it was appended, and dropping it
    would report a smaller file than exists.
    """
    if not path.is_file():
        return None, ""
    count = 0
    latest = ""
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        count += 1
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        stamp = row.get("ts") or row.get("timestamp") or ""
        if isinstance(stamp, str) and stamp[:10] > latest:
            latest = stamp[:10]
    return count, latest


def _memory_documents(target: Path) -> list[Path]:
    """The curated memories, without the index or the proposal ledgers.

    `MEMORY.md` is the index and `claude-md.accepted/rejected/proposal.md` are
    the compound loop's ledgers. Counting every `.md` reports the bookkeeping
    as if it were memory.
    """
    if not target.is_dir():
        return []
    return sorted(
        p
        for p in target.glob("*.md")
        if p.name != "MEMORY.md" and not p.name.startswith("claude-md.")
    )


def _human_bytes(n: int) -> str:
    """Bytes at the scale a curated memory file actually reaches."""
    if n < 1000:
        return f"{n} B"
    return f"{n / 1000:.1f} KB"


@memory.command("status")
@_MEMORY_DIR_OPTION
def status(memory_dir: Path | None) -> None:
    """Report where this project's memory lives and what is in it."""
    target = memory_dir or _project_memory_dir()
    if memory_dir is None:
        from lazy_harness.core.project_identity import LOCAL_PREFIX, project_key

        key = project_key(Path.cwd())
        reason = (
            " — no git remote, so memory stays out of the shared store"
            if key.startswith(f"{LOCAL_PREFIX}/")
            else ""
        )
        click.echo(f"{'Project':<8} {key}{reason}")
    click.echo(f"{'Store':<8} {target}")
    click.echo("")

    index = target / "MEMORY.md"
    if index.is_file():
        text = index.read_text()
        click.echo(
            f"  MEMORY.md        {len(text.splitlines())} lines · "
            f"{_human_bytes(len(text.encode()))}"
        )
    else:
        click.echo("  MEMORY.md        absent")

    docs = _memory_documents(target)
    total = sum(d.stat().st_size for d in docs)
    click.echo(f"  memories         {len(docs)} files · {_human_bytes(total)}")

    for name in ("decisions", "failures", "grades"):
        count, last = _jsonl_summary(target / f"{name}.jsonl")
        if count is None:
            continue
        tail = f" · last {last}" if last else ""
        click.echo(f"  {name + '.jsonl':<16} {count} records{tail}")

    pending = len(parse_proposals(_read_text(target / "claude-md.proposal.md")))
    rejected = _count_rules(target / "claude-md.rejected.md")
    accepted = _count_rules(target / "claude-md.accepted.md")
    click.echo(f"  proposals        {pending} pending · {rejected} rejected · {accepted} accepted")

    if memory_dir is not None:
        return
    legacy = _legacy_memory_dir()
    if legacy == target or not any(legacy.glob("*")):
        return
    index = legacy / "MEMORY.md"
    lines = len(index.read_text().splitlines()) if index.is_file() else 0
    click.echo("")
    click.echo(f"Also present, outside the store: {legacy}")
    click.echo(
        f"  MEMORY.md {lines} lines · {len(_memory_documents(legacy))} memories — "
        "classify it: lh memory legacy-check"
    )


@memory.group("proposals")
def proposals() -> None:
    """Review compound-loop claude-md proposals: list, accept, reject."""


@proposals.command("list")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit the listing as JSON, indices included, for `proposals apply`.",
)
@_MEMORY_DIR_OPTION
def proposals_list(as_json: bool, memory_dir: Path | None) -> None:
    """List pending claude-md proposals."""
    pending_file, _, pending = _load_pending(memory_dir)
    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "index": i,
                        "timestamp": p.timestamp,
                        "rule": p.rule,
                        "rationale": p.rationale,
                    }
                    for i, p in enumerate(pending, start=1)
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not pending:
        click.echo(f"No pending claude-md proposals at {pending_file}.")
        return
    click.echo(f"Pending claude-md proposals ({pending_file}):")
    for i, p in enumerate(pending, start=1):
        excerpt = p.rule if len(p.rule) <= 72 else p.rule[:69] + "..."
        click.echo(f"  {i:>3}  {p.timestamp[:10] or '????-??-??'}  {excerpt}")
    click.echo(
        "\nAccept: lh memory proposals accept <N> — reject: "
        'lh memory proposals reject <N> --reason "..."\n'
        "Whole queue at once: lh memory proposals list --json, then "
        "lh memory proposals apply --verdicts <file>"
    )


_VERDICTS = ("accept", "reject")


def _parse_verdicts(raw: object, pending_count: int) -> list[tuple[int, str, str]]:
    """Validate the whole verdict document before a single write happens.

    Half-applying a hundred verdicts and then failing leaves a queue nobody can
    reconcile against the listing the verdicts were written from, so every
    check runs up front.
    """
    if not isinstance(raw, list):
        raise click.ClickException(
            "The verdicts document must be a JSON list of "
            '{"index": N, "verdict": "accept"|"reject", "reason": "..."} objects.'
        )
    seen: set[int] = set()
    parsed: list[tuple[int, str, str]] = []
    for i, item in enumerate(raw):
        where = f"entry {i + 1}"
        if not isinstance(item, dict):
            raise click.ClickException(f"{where}: expected an object, got {type(item).__name__}.")
        index = item.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            raise click.ClickException(f"{where}: 'index' must be an integer.")
        if index < 1 or index > pending_count:
            raise click.ClickException(
                f"{where}: no proposal #{index} — {pending_count} pending. "
                "Re-read the queue with `lh memory proposals list --json`."
            )
        if index in seen:
            raise click.ClickException(f"{where}: duplicate verdict for proposal #{index}.")
        seen.add(index)
        verdict = item.get("verdict")
        if verdict not in _VERDICTS:
            raise click.ClickException(
                f"{where}: unknown verdict {verdict!r} — expected 'accept' or 'reject'."
            )
        reason = item.get("reason") or ""
        if verdict == "reject" and not str(reason).strip():
            raise click.ClickException(
                f"{where}: a rejection needs a 'reason'. The reason is what the "
                "immunity registry teaches the grader; without it the rule comes back."
            )
        parsed.append((index, verdict, str(reason)))
    return parsed


@proposals.command("apply")
@click.option(
    "--verdicts",
    "verdicts_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="JSON list of {index, verdict, reason} against `proposals list --json`.",
)
@_MEMORY_DIR_OPTION
def proposals_apply(verdicts_file: Path, memory_dir: Path | None) -> None:
    """Accept or reject many proposals in one pass.

    Indices are resolved against the listing the verdicts were written from.
    `accept N`/`reject N` index into a file that shrinks under them, so a caller
    draining 1, 2, 3 in that order silently hits the wrong entries; this applies
    them back-to-front so that footgun is gone.
    """
    pending_file, text, pending = _load_pending(memory_dir)
    try:
        raw = json.loads(verdicts_file.read_text())
    except ValueError as exc:
        raise click.ClickException(f"{verdicts_file} is not valid JSON: {exc}") from exc

    decisions = _parse_verdicts(raw, len(pending))
    if not decisions:
        click.echo("No verdicts — nothing to apply.")
        return

    today = date.today().isoformat()
    accepted_rules: list[str] = []
    n_accepted = n_rejected = 0
    # Descending: every removal shifts the positions after it.
    for index, verdict, reason in sorted(decisions, key=lambda d: -d[0]):
        target = pending[index - 1]
        if verdict == "accept":
            _append_block(
                pending_file.with_name("claude-md.accepted.md"),
                "<!-- accepted claude-md proposals (append-only). -->\n\n",
                _format_entry_block(target, [f"accepted: {today}"]),
            )
            accepted_rules.append(target.rule)
            n_accepted += 1
        else:
            _append_block(
                pending_file.with_name("claude-md.rejected.md"),
                "<!-- rejected claude-md proposals (append-only immunity registry). -->\n\n",
                _format_entry_block(target, [f"rejected: {today}", f"reason: {reason}"]),
            )
            n_rejected += 1
        text = _remove_proposal(text, pending, index - 1)
    _atomic_write(pending_file, text)

    remaining = len(parse_proposals(text))
    click.echo(f"{n_accepted} accepted · {n_rejected} rejected · {remaining} pending")
    if accepted_rules:
        click.echo("\nAccepted rules were NOT applied automatically — merge them yourself:")
        for rule in reversed(accepted_rules):
            click.echo(f"  · {rule}")


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


def _known_project_keys(knowledge_root: Path | None) -> set[str]:
    """Project keys with distilled memory already in the knowledge store.

    Mirrors the area lookup `memory_migration.plan_migration` does before
    building a target path — read-only, fail-soft for the same reason: an
    unusable store means nothing is known yet, not an error.
    """
    if knowledge_root is None:
        return set()
    try:
        from lazy_harness.knowledge.marker import read_marker

        area = read_marker(knowledge_root).memory
    except Exception:  # noqa: BLE001 — an unusable store yields no keys, not a crash
        return set()
    if not area:
        return set()
    area_root = knowledge_root / area

    from lazy_harness.core.memory_store import store_memory_dirs

    keys: set[str] = set()
    for store_dir in store_memory_dirs(knowledge_root):
        try:
            keys.add("/".join(store_dir.relative_to(area_root).parts))
        except ValueError:
            continue
    return keys


def _project_claude_mds(cfg: Config, known_keys: set[str]) -> list[tuple[str, Path]]:
    """`(label, path)` for every reachable CLAUDE.md of a project the memory
    stack already knows about.

    Scans the profile `roots` used for cwd-based profile routing, one level
    deep — that is where a checkout lives, `roots` names the directory that
    holds checkouts. `core.project_identity.project_key` is the resolver this
    command uses deliberately (see `tests/unit/hooks/builtins/test_shared.py`
    for the integration test asserting it agrees with the other resolver on
    where a worktree's root is): membership in `known_keys` is checked against
    its *real* output for each candidate, never guessed from the directory
    name, so it is exact regardless of how the checkout is named locally.
    """
    from lazy_harness.core.paths import expand_path
    from lazy_harness.core.project_identity import project_key

    found: list[tuple[str, Path]] = []
    seen_paths: set[Path] = set()
    for entry in cfg.profiles.items.values():
        for root in entry.roots:
            root_path = expand_path(root)
            if not root_path.is_dir():
                continue
            for candidate in sorted(root_path.iterdir()):
                if not candidate.is_dir() or candidate in seen_paths:
                    continue
                seen_paths.add(candidate)
                key = project_key(candidate)
                if key not in known_keys:
                    continue
                claude_md = candidate / "CLAUDE.md"
                if claude_md.is_file():
                    found.append((f"project:{key}", claude_md))
    return found


@memory.command("rightsize")
def rightsize() -> None:
    """List every CLAUDE.md the harness can reach and which ceiling it breaches.

    Read-only (ADR-030, Track 1b of the September 2026 harness improvements
    design). Covers profile contracts — `<profile config_dir>/CLAUDE.md`,
    loaded on every session in that profile — and the CLAUDE.md of every
    project the memory stack already has distilled memory for. Thresholds are
    the same ones `pre_tool_use_memory_size` warns against, read from the same
    `[hooks.pre_tool_use]` config so the two cannot silently disagree.
    """
    from lazy_harness.core.profiles import list_profiles
    from lazy_harness.hooks.builtins._shared import knowledge_root_for
    from lazy_harness.hooks.builtins.pre_tool_use_memory_size import load_claude_md_thresholds

    cf = config_file()
    try:
        cfg = load_config(cf) if cf.is_file() else Config()
    except ConfigError as exc:
        click.echo(f"Config invalid: {exc}", err=True)
        raise SystemExit(1) from exc

    max_lines, max_bytes = load_claude_md_thresholds(cf)

    entries: list[tuple[str, Path]] = []
    for profile in list_profiles(cfg):
        if not profile.exists:
            continue
        claude_md = profile.config_dir / "CLAUDE.md"
        if claude_md.is_file():
            entries.append((f"profile:{profile.name}", claude_md))

    known_keys = _known_project_keys(knowledge_root_for(cfg))
    if known_keys:
        entries.extend(_project_claude_mds(cfg, known_keys))

    if not entries:
        click.echo("No CLAUDE.md files found.")
        return

    breach_count = 0
    for label, path in entries:
        text = path.read_text(errors="replace")
        lines = len(text.splitlines())
        size = len(text.encode("utf-8"))
        breaches: list[str] = []
        if lines > max_lines:
            breaches.append(f"{lines} lines > {max_lines}")
        if size > max_bytes:
            breaches.append(f"{size} bytes > {max_bytes}")
        if breaches:
            breach_count += 1
        breach_text = "; ".join(breaches) if breaches else "-"
        click.echo(f"{label:<40} {lines:>6} lines  {size:>8} bytes  {breach_text}")

    click.echo("")
    click.echo(
        f"{breach_count}/{len(entries)} over threshold ({max_lines} lines / {max_bytes} bytes)"
    )


@memory.command("migrate")
@click.option("--apply", "do_apply", is_flag=True, help="Move the files. Off by default.")
def memory_migrate(do_apply: bool) -> None:
    """Move project memory to its identity-keyed home in the knowledge store.

    Dry by default: this moves documents a person curated over months, and the
    plan is worth reading before any of it moves.

    Nothing is merged. A target that already holds files is reported as a
    conflict and left alone — two machines that each wrote a MEMORY.md have two
    curated documents, and choosing one silently loses the other.
    """
    from lazy_harness.core.memory_migration import apply_migration, plan_migration
    from lazy_harness.core.profiles import list_profiles
    from lazy_harness.hooks.builtins._shared import knowledge_root_for

    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    root = knowledge_root_for(cfg)
    if root is None:
        click.echo("No knowledge store; nothing to migrate into.", err=True)
        raise SystemExit(1)

    profile_dirs = [p.config_dir for p in list_profiles(cfg) if p.exists]
    moves = plan_migration(profile_dirs, knowledge_root=root)
    movable = [m for m in moves if m.target is not None]

    click.echo(f"{len(moves)} legacy memory directories")
    click.echo(f"{len(movable)} would move into {root}")
    click.echo("")

    reasons: dict[str, int] = {}
    for m in moves:
        if m.target is None:
            reasons[m.reason] = reasons.get(m.reason, 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        click.echo(f"  {count:4} left alone: {reason}")
    if reasons:
        click.echo("")

    for m in movable:
        click.echo(f"  {m.source.parent.name}")
        click.echo(f"    -> {m.target.relative_to(root)}")

    if not do_apply:
        click.echo("")
        click.echo("Dry run. Re-run with --apply to move them.")
        return

    result = apply_migration(movable)
    click.echo("")
    click.echo(f"Moved {result.moved}.")
    for m in result.conflicts:
        click.echo(f"  conflict: {m.target} already holds files; left {m.source} in place")
    for m, err in result.failures:
        click.echo(f"  failed: {m.source}: {err}")
