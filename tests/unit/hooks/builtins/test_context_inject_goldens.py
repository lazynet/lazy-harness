"""Byte goldens for `context_inject`, one per branch, captured pre-migration.

The third hook the runner migration touches, and the only one of the three with
no verdict at all: it always exits 0 and always prints one JSON object on
stdout, so what a migration can break here is the *content* — a section dropped,
a banner nested back inside `hookSpecificOutput`, a truncation notice that stops
naming what it dropped.

Branches, read off `main()` and the section builders it calls:

* stdin — a real payload, empty, and malformed (the hook carries on regardless);
* config — absent, unparseable (both fall back to the same defaults), valid;
* git — outside a repo, a clean repo, a dirty one, and a detached HEAD;
* handoff — legacy without frontmatter, fresh, and each of the three staleness
  verdicts, plus the pre-compact summary on its own and alongside;
* proposals — pending, and a queue at the cap that adds the halt notice;
* episodic — decisions alone, and decisions plus failures with prevention;
* graphify — fresh outside a repo, fresh inside one, stale, and malformed;
* repo map — in scope, out of scope, and over the character cap;
* last session, LazyNorth, and the qmd section enabled with no binary reachable;
* truncation — sections dropped in priority order, and the case where dropping
  proposals promotes the one-line summary into the banner.

Two things are normalised, both because they are properties of the machine and
not of the hook: git's abbreviated commit hash, whose width git picks from the
object count, and nothing else — every other varying input (commit timestamps,
file mtimes, the timezone) is pinned to a fixed value instead.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    assert_golden,
    golden_path,
    normalise_run,
    pinned_env,
    run_through_runner,
)

HOOK = "context-inject"

SESSION = "0193c0de-aaaa-bbbb-cccc-ddddeeeeffff"
OTHER_SESSION = "7fffabcd-9999-8888-7777-666655554444"

#: Fixed commit time, so graphify's staleness dates are the same everywhere.
#: Rendered in UTC, which `pinned_env` sets in the child.
COMMIT_EPOCH = 1767312245
DAY = 86400

BASE_CONFIG = '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n'


@dataclass
class World:
    """The pinned machine one case runs against."""

    tmp: Path
    home: Path
    config_dir: Path
    data_dir: Path
    agent_dir: Path
    work: Path
    project_dir: Path
    memory_dir: Path
    transcript: Path
    knowledge_root: Path
    lazynorth_dir: Path

    def config(self, extra: str = "") -> None:
        (self.config_dir / "config.toml").write_text(BASE_CONFIG + extra)

    def raw_config(self, text: str) -> None:
        (self.config_dir / "config.toml").write_text(text)

    def memory_file(self, name: str, text: str) -> Path:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        path = self.memory_dir / name
        path.write_text(text)
        return path

    def session_jsonl(self, session: str, *, mtime: float | None = None) -> Path:
        path = self.project_dir / f"{session}.jsonl"
        path.write_text('{"type":"user"}\n')
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run git in `work` with every ambient config source shut off."""
        env = {
            "HOME": str(self.home),
            "PATH": os.environ.get("PATH", ""),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "Golden",
            "GIT_AUTHOR_EMAIL": "golden@example.invalid",
            "GIT_COMMITTER_NAME": "Golden",
            "GIT_COMMITTER_EMAIL": "golden@example.invalid",
            "GIT_AUTHOR_DATE": f"{COMMIT_EPOCH} +0000",
            "GIT_COMMITTER_DATE": f"{COMMIT_EPOCH} +0000",
        }
        return subprocess.run(
            ["git", *args],
            cwd=self.work,
            env=env,
            capture_output=True,
            text=True,
            check=check,
        )

    def init_repo(self) -> None:
        self.git("init", "-q", "-b", "main")
        (self.work / "README.md").write_text("# demo\n")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "seed the repo")

    def graph_json(self, text: str, *, mtime: float) -> None:
        out = self.work / "graphify-out"
        out.mkdir(parents=True, exist_ok=True)
        path = out / "graph.json"
        path.write_text(text)
        os.utime(path, (mtime, mtime))


Build = Callable[[World], None]


@dataclass(frozen=True)
class Case:
    id: str
    build: Build
    #: Raw stdin; `None` sends the ordinary SessionStart payload.
    raw_stdin: str | None = None


# --------------------------------------------------------------------------- #
# Fixtures the cases share
# --------------------------------------------------------------------------- #

_GRAPH = json.dumps(
    {
        "nodes": [
            {"id": "a", "community": 1},
            {"id": "b", "community": 1},
            {"id": "c", "community": 2},
            {"id": "d", "community": 2},
            {"id": "e", "community": 3},
            "not-a-dict",
            {"id": "f"},
            {"id": "g", "community": "nope"},
        ],
        "edges": [["a", "b"], ["b", "c"]],
    }
)

_HANDOFF_BODY = "Pendiente:\n- close the runner slice\n- capture the goldens\n"


def _handoff(session: str, source_mtime: float) -> str:
    return f"---\nsession_id: {session}\nsource_mtime: {source_mtime}\n---\n{_HANDOFF_BODY}"


def _proposals(n: int) -> str:
    """`n` pending proposals in the shape `lh memory proposals` numbers.

    The bullet prefixes are what `parse_proposals` counts; prose under a
    heading it does not recognise counts as zero, which would make the
    queue-at-the-cap branch unreachable.
    """
    blocks = [
        f"## 2026-09-{day:02d}\n"
        f"- **Rule:** proposal {day}\n"
        f"- **Rationale:** because of reason {day}\n"
        for day in range(1, n + 1)
    ]
    return "<!-- archived: nothing here counts -->\n" + "\n".join(blocks)


_PROPOSAL = _proposals(1)


_DECISIONS = "\n".join(json.dumps({"summary": f"decision {i}"}) for i in range(1, 5))
_FAILURES = "\n".join(
    json.dumps({"summary": f"failure {i}", "prevention": f"prevent {i}"}) for i in range(1, 4)
)

_SESSION_MD = """---
project: work
date: 2026-09-10
messages: 42
---

## User

Capture the goldens before migrating the runner, please.
"""

_LAZYNORTH_UNIVERSAL = """---
tags: north
---
# LazyNorth

Brújula estratégica del año.

## Principios
- Ship before perfect.
- Simplicidad agresiva.
"""

_LAZYNORTH_PROFILE = """# LazyNorth Lazy

Foco trimestral del perfil.

## Goals
- Homelab cerrado.
"""

_REPO_MAP = "# Repos\n\n- lazy-harness — the harness itself\n- lazy-knowledge — the store\n"


# --------------------------------------------------------------------------- #
# Cases
# --------------------------------------------------------------------------- #


def _nothing(world: World) -> None:
    """No config, no memory, no repo: the empty-project branch."""


def _valid_config(world: World) -> None:
    world.config()


def _unparseable_config(world: World) -> None:
    world.raw_config("[context_inject\nenabled = true")


def _clean_repo(world: World) -> None:
    world.init_repo()


def _dirty_repo(world: World) -> None:
    world.init_repo()
    (world.work / "README.md").write_text("# demo\nmodified\n")
    (world.work / "scratch.txt").write_text("untracked\n")


def _detached_head(world: World) -> None:
    world.init_repo()
    world.git("checkout", "-q", "--detach")


def _handoff_legacy(world: World) -> None:
    world.memory_file("handoff.md", _HANDOFF_BODY)


def _handoff_fresh(world: World) -> None:
    world.session_jsonl(SESSION, mtime=COMMIT_EPOCH)
    world.memory_file("handoff.md", _handoff(SESSION, COMMIT_EPOCH))


def _handoff_no_jsonl(world: World) -> None:
    world.memory_file("handoff.md", _handoff(SESSION, COMMIT_EPOCH))


def _handoff_session_mismatch(world: World) -> None:
    world.session_jsonl(OTHER_SESSION, mtime=COMMIT_EPOCH)
    world.memory_file("handoff.md", _handoff(SESSION, COMMIT_EPOCH))


def _handoff_session_grew(world: World) -> None:
    world.session_jsonl(SESSION, mtime=COMMIT_EPOCH + DAY)
    world.memory_file("handoff.md", _handoff(SESSION, COMMIT_EPOCH))


def _pre_compact_only(world: World) -> None:
    world.memory_file(
        "pre-compact-summary.md",
        "<!-- written at compaction -->\n## Recent decisions\n- keep the runner thin\n",
    )


def _handoff_and_pre_compact(world: World) -> None:
    _handoff_fresh(world)
    _pre_compact_only(world)


def _proposals_pending(world: World) -> None:
    world.memory_file("claude-md.proposal.md", _PROPOSAL)


def _proposals_queue_full(world: World) -> None:
    world.config("\n[compound_loop]\nmax_pending_proposals = 3\n")
    world.memory_file("claude-md.proposal.md", _proposals(3))


def _episodic_decisions_only(world: World) -> None:
    world.memory_file("decisions.jsonl", _DECISIONS)


def _episodic_both(world: World) -> None:
    world.memory_file("decisions.jsonl", _DECISIONS)
    world.memory_file("failures.jsonl", _FAILURES)


def _graphify_fresh_no_git(world: World) -> None:
    world.graph_json(_GRAPH, mtime=COMMIT_EPOCH)


def _graphify_fresh_in_repo(world: World) -> None:
    world.init_repo()
    world.graph_json(_GRAPH, mtime=COMMIT_EPOCH + DAY)


def _graphify_stale(world: World) -> None:
    world.init_repo()
    world.graph_json(_GRAPH, mtime=COMMIT_EPOCH - DAY)


def _graphify_malformed(world: World) -> None:
    world.graph_json("{not json", mtime=COMMIT_EPOCH)


def _graphify_disabled(world: World) -> None:
    world.config("\n[context_inject]\ngraphify_surface_enabled = false\n")
    world.graph_json(_GRAPH, mtime=COMMIT_EPOCH)


def _repo_map_in_scope(world: World) -> None:
    (world.agent_dir / "docs").mkdir(parents=True, exist_ok=True)
    (world.agent_dir / "docs" / "repos.md").write_text(_REPO_MAP)
    world.config(f'\n[context_inject]\nrepo_map_scope = "{world.work.parent}"\n')


def _repo_map_truncated(world: World) -> None:
    (world.agent_dir / "docs").mkdir(parents=True, exist_ok=True)
    (world.agent_dir / "docs" / "repos.md").write_text(_REPO_MAP * 8)
    world.config(
        f'\n[context_inject]\nrepo_map_scope = "{world.work.parent}"\nrepo_map_max_chars = 120\n'
    )


def _repo_map_out_of_scope(world: World) -> None:
    (world.agent_dir / "docs").mkdir(parents=True, exist_ok=True)
    (world.agent_dir / "docs" / "repos.md").write_text(_REPO_MAP)
    world.config(f'\n[context_inject]\nrepo_map_scope = "{world.tmp / "elsewhere"}"\n')


def _last_session(world: World) -> None:
    from lazy_harness.knowledge.marker import write_marker

    write_marker(world.knowledge_root)
    sessions = world.knowledge_root / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "2026-09-10-work.md").write_text(
        _SESSION_MD.replace(
            "project: work\n",
            "project_key: local/work\nsource_identity: work\n"
            f'project_root: "{world.work.resolve()}"\n',
        )
    )
    world.config(
        f'\n[knowledge]\nroot = "{world.knowledge_root}"\n'
        f'\n[profiles.work]\nconfig_dir = "{world.agent_dir}"\n'
    )


def _lazynorth(world: World) -> None:
    world.lazynorth_dir.mkdir(parents=True, exist_ok=True)
    (world.lazynorth_dir / "LazyNorth.md").write_text(_LAZYNORTH_UNIVERSAL)
    (world.lazynorth_dir / "LazyNorth-Lazy.md").write_text(_LAZYNORTH_PROFILE)
    world.config(
        f'\n[lazynorth]\nenabled = true\npath = "{world.lazynorth_dir}"\n'
        '\n[profiles]\ndefault = "lazy"\n'
        f'\n[profiles.lazy]\nconfig_dir = "{world.agent_dir}"\n'
        'roots = ["~"]\nlazynorth_doc = "LazyNorth-Lazy.md"\n'
    )


def _qmd_enabled(world: World) -> None:
    world.init_repo()
    world.config("\n[context_inject]\nqmd_suggest_enabled = true\n")


def _truncation(world: World) -> None:
    world.config("\n[context_inject]\nmax_body_chars = 220\n")
    _handoff_fresh(world)
    world.memory_file("decisions.jsonl", _DECISIONS)
    world.memory_file("failures.jsonl", _FAILURES)


def _truncation_promotes_proposals_summary(world: World) -> None:
    world.config("\n[context_inject]\nmax_body_chars = 120\n")
    _handoff_fresh(world)
    world.memory_file("claude-md.proposal.md", _proposals(2))
    world.memory_file("decisions.jsonl", _DECISIONS)


CASES: list[Case] = [
    Case(id="no-config-empty-project", build=_nothing),
    Case(id="stdin-empty", build=_nothing, raw_stdin=""),
    Case(id="stdin-malformed-json", build=_nothing, raw_stdin="not json at all"),
    Case(id="config-unparseable", build=_unparseable_config),
    Case(id="config-valid-defaults", build=_valid_config),
    Case(id="git-clean-repo", build=_clean_repo),
    Case(id="git-dirty-repo", build=_dirty_repo),
    Case(id="git-detached-head", build=_detached_head),
    Case(id="handoff-legacy-without-frontmatter", build=_handoff_legacy),
    Case(id="handoff-fresh", build=_handoff_fresh),
    Case(id="handoff-stale-no-session-jsonl", build=_handoff_no_jsonl),
    Case(id="handoff-stale-session-mismatch", build=_handoff_session_mismatch),
    Case(id="handoff-stale-session-grew", build=_handoff_session_grew),
    Case(id="pre-compact-summary-only", build=_pre_compact_only),
    Case(id="handoff-and-pre-compact-summary", build=_handoff_and_pre_compact),
    Case(id="proposals-pending", build=_proposals_pending),
    Case(id="proposals-queue-at-the-cap", build=_proposals_queue_full),
    Case(id="episodic-decisions-only", build=_episodic_decisions_only),
    Case(id="episodic-decisions-and-failures", build=_episodic_both),
    Case(id="graphify-fresh-outside-a-repo", build=_graphify_fresh_no_git),
    Case(id="graphify-fresh-in-a-repo", build=_graphify_fresh_in_repo),
    Case(id="graphify-stale", build=_graphify_stale),
    Case(id="graphify-malformed-json", build=_graphify_malformed),
    Case(id="graphify-disabled", build=_graphify_disabled),
    Case(id="repo-map-in-scope", build=_repo_map_in_scope),
    Case(id="repo-map-over-the-cap", build=_repo_map_truncated),
    Case(id="repo-map-out-of-scope", build=_repo_map_out_of_scope),
    Case(id="last-session-found", build=_last_session),
    Case(id="lazynorth-universal-and-profile", build=_lazynorth),
    Case(id="qmd-suggest-enabled-without-binary", build=_qmd_enabled),
    Case(id="truncation-drops-in-priority-order", build=_truncation),
    Case(id="truncation-promotes-proposals-summary", build=_truncation_promotes_proposals_summary),
]


def _world(tmp_path: Path) -> World:
    home = tmp_path / "home"
    agent_dir = tmp_path / "claude"
    work = tmp_path / "repos" / "work"
    project_dir = agent_dir / "projects" / "-repos-work"
    world = World(
        tmp=tmp_path,
        home=home,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        agent_dir=agent_dir,
        work=work,
        project_dir=project_dir,
        memory_dir=project_dir / "memory",
        transcript=project_dir / f"{SESSION}.jsonl",
        knowledge_root=tmp_path / "knowledge",
        lazynorth_dir=tmp_path / "lazynorth",
    )
    for d in (home, world.config_dir, world.data_dir, work, project_dir):
        d.mkdir(parents=True, exist_ok=True)
    return world


def _run(world: World, case: Case):  # noqa: ANN202 - HookRun, imported for typing only
    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    else:
        stdin = json.dumps(
            {
                "hook_event_name": "SessionStart",
                "session_id": SESSION,
                "transcript_path": str(world.transcript),
                "cwd": str(world.work),
            }
        )
    env = pinned_env(
        home=world.home,
        config_dir=world.config_dir,
        data_dir=world.data_dir,
        agent_config_dir=world.agent_dir,
    )
    # A `qmd` reachable from the child would add a section on one machine and
    # not another; the pinned PATH is what keeps that out of the goldens.
    assert shutil.which("qmd", path=env["PATH"]) is None

    run = run_through_runner(HOOK, stdin_text=stdin, cwd=world.work, env=env)

    rules: list[tuple[str, str]] = []
    head = world.git("log", "-1", "--format=%h", check=False)
    if head.returncode == 0 and head.stdout.strip():
        # git picks the abbreviation width from the repository's object count
        # and `core.abbrev`, so the hash's *length* is a property of the machine
        # rather than of the hook. Everything else the commit contributes is
        # pinned: author, committer, message and both dates.
        rules.append((head.stdout.strip(), "<SHA>"))
    return normalise_run(run, tuple(rules))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    world = _world(tmp_path)
    case.build(world)

    assert_golden(HOOK, case.id, _run(world, case))


#: The payloads the runner cannot use. `context_inject` is informational, so
#: decision 3's table gives it exit 0 with a warning on stderr — and no stdout.
#: That is a real loss on this branch: both cases used to emit the full
#: injection, because the hook reads nothing from the payload it cannot do
#: without. The table does not carve out a hook that would have coped.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset({"stdin-empty", "stdin-malformed-json"})


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case_id", [c.id for c in CASES if c.id not in UNUSABLE_PAYLOAD_CASE_IDS])
def test_every_branch_emits_one_json_object_on_stdout_and_exits_0(case_id: str) -> None:
    """This hook has no verdict: it always answers, always on stdout, always 0."""
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stderr"] == ""
    payload = json.loads(golden["stdout"])
    assert set(payload) == {"hookSpecificOutput", "systemMessage"}
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"


@pytest.mark.parametrize("case_id", [c.id for c in CASES if c.id not in UNUSABLE_PAYLOAD_CASE_IDS])
def test_the_banner_stays_at_the_top_level(case_id: str) -> None:
    """`systemMessage` nested inside `hookSpecificOutput` parses and is discarded.

    That is the regression `f7a2432` fixed; freezing it here means the runner
    migration cannot reintroduce it without a golden going red.
    """
    payload = json.loads(json.loads(golden_path(HOOK, case_id).read_text())["stdout"])

    assert isinstance(payload["systemMessage"], str)
    assert payload["systemMessage"]
    assert "systemMessage" not in payload["hookSpecificOutput"]


def test_the_empty_project_branch_says_so() -> None:
    payload = json.loads(
        json.loads(golden_path(HOOK, "no-config-empty-project").read_text())["stdout"]
    )

    assert payload["hookSpecificOutput"]["additionalContext"] == "New project, no prior context."
    assert payload["systemMessage"] == "Session context loaded (new project)"


def test_no_golden_carries_an_unnormalised_temp_path() -> None:
    """A leaked tmp path would make the golden pass only on the machine that
    captured it — the failure mode this whole harness exists to prevent."""
    for case in CASES:
        raw = golden_path(HOOK, case.id).read_text()
        assert "/pytest-of-" not in raw, case.id
        assert "/var/folders/" not in raw, case.id


def _body(case_id: str) -> str:
    payload = json.loads(json.loads(golden_path(HOOK, case_id).read_text())["stdout"])
    return str(payload["hookSpecificOutput"]["additionalContext"])


def test_the_queue_at_the_cap_carries_the_halt_notice() -> None:
    """A halted producer is visible in the ordinary case, not only under budget
    pressure — the whole point of the cap is that stopping is noticed."""
    body = _body("proposals-queue-at-the-cap")

    assert "⚠ 3 claude-md proposal(s) pending (oldest 2026-09-01)" in body
    assert "the queue is full" in body
    assert "the queue is full" not in _body("proposals-pending")


def test_dropping_proposals_promotes_the_one_line_summary() -> None:
    """Pending proposals are never silently hidden by truncation."""
    body = _body("truncation-promotes-proposals-summary")

    assert body.startswith("[truncated]\n")
    assert "⚠ 2 claude-md proposal(s) pending" in body
    assert len(body) <= 120
    # The section itself is gone; only the one-liner survives.
    assert "## Proposals to review" not in body


def test_the_three_staleness_verdicts_are_distinguishable() -> None:
    """Each stale branch names a different reason; identical text would let two
    of them collapse into one without a golden noticing."""
    reasons = {
        case_id: _body(case_id).splitlines()[2]
        for case_id in (
            "handoff-stale-no-session-jsonl",
            "handoff-stale-session-mismatch",
            "handoff-stale-session-grew",
        )
    }

    assert len(set(reasons.values())) == 3
    assert reasons["handoff-stale-session-mismatch"].count("0193c0de") == 1


def test_the_fresh_handoff_carries_no_staleness_warning() -> None:
    assert "may be stale" not in _body("handoff-fresh")
    assert "may be stale" in _body("handoff-stale-session-grew")


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_emits_no_injection_at_all(case_id: str) -> None:
    """Decision 3's table, informational column: exit 0, warning, empty stdout.

    Both goldens used to carry the whole banner. `context_inject` reads almost
    nothing off the payload, so it was one of the hooks that genuinely coped
    with an empty one — and the injection it emitted there is what the table
    costs. Named rather than hidden: the alternative is a per-hook exception to
    a policy whose value is that it has none.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert "unparseable payload" in golden["stderr"]
