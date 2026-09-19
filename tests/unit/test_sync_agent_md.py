"""Tests for the segmented system-doc generator (lh profile sync-agent-md)."""

from __future__ import annotations

from pathlib import Path


def _adapter():
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    return ClaudeCodeAdapter()


def _seed_profile(
    profiles_dir: Path,
    name: str,
    *,
    head: str | None = "# head\n",
    tail: str | None = "# tail\n",
) -> Path:
    p = profiles_dir / name
    p.mkdir(parents=True)
    if head is not None:
        (p / "head.md").write_text(head)
    if tail is not None:
        (p / "tail.md").write_text(tail)
    return p


def _seed_common(profiles_dir: Path, body: str = "# common\n") -> None:
    common = profiles_dir / "_common"
    common.mkdir(parents=True, exist_ok=True)
    (common / "common.md").write_text(body)


def test_sync_profiles_writes_concatenation(tmp_path: Path) -> None:
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir, body="# common rules\n")
    _seed_profile(profiles_dir, "lazy", head="# I am lazy\n", tail="# lazy ctx\n")

    results = sync_profiles(profiles_dir, _adapter())

    assert len(results) == 1
    r = results[0]
    assert r.profile == "lazy"
    assert r.action == "written"

    out = (profiles_dir / "lazy" / "CLAUDE.md").read_text()
    assert "# I am lazy" in out
    assert "# common rules" in out
    assert "# lazy ctx" in out
    assert out.index("# I am lazy") < out.index("# common rules") < out.index("# lazy ctx")


def test_sync_profiles_is_idempotent(tmp_path: Path) -> None:
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir)
    _seed_profile(profiles_dir, "lazy")

    sync_profiles(profiles_dir, _adapter())
    second = sync_profiles(profiles_dir, _adapter())

    assert [r.action for r in second] == ["unchanged"]


def test_sync_profiles_skips_dirs_without_segments(tmp_path: Path) -> None:
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir)
    _seed_profile(profiles_dir, "lazy")
    _seed_profile(profiles_dir, "partial", tail=None)
    (profiles_dir / "flat").mkdir()
    (profiles_dir / "flat" / "CLAUDE.md").write_text("hand-written\n")

    results = sync_profiles(profiles_dir, _adapter())
    by_name = {r.profile: r for r in results}

    assert by_name["lazy"].action == "written"
    assert by_name["partial"].action == "skipped"
    assert by_name["flat"].action == "skipped"
    assert (profiles_dir / "flat" / "CLAUDE.md").read_text() == "hand-written\n"


def test_sync_profiles_raises_when_common_missing(tmp_path: Path) -> None:
    import pytest

    from lazy_harness.core.sync_agent_md import SyncError, sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_profile(profiles_dir, "lazy")

    with pytest.raises(SyncError, match="common.md"):
        sync_profiles(profiles_dir, _adapter())


def test_sync_profiles_skips_underscore_dirs(tmp_path: Path) -> None:
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir)
    _seed_profile(profiles_dir, "lazy")
    (profiles_dir / "_common" / "CLAUDE.head.md").write_text("h\n")
    (profiles_dir / "_common" / "CLAUDE.tail.md").write_text("t\n")

    results = sync_profiles(profiles_dir, _adapter())
    profiles = {r.profile for r in results}
    assert profiles == {"lazy"}


def test_sync_profiles_noop_for_null_adapter(tmp_path: Path) -> None:
    """Adapters without a system doc return empty list — no files written."""
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir)
    _seed_profile(profiles_dir, "lazy")

    results = sync_profiles(profiles_dir, get_agent("null"))
    assert results == []
    assert not (profiles_dir / "lazy" / "CLAUDE.md").exists()


def test_generated_header_carries_the_writing_version(tmp_path: Path) -> None:
    """Decision 9: a generated doc declares the lazy-harness version that
    wrote it, so a stale CLAUDE.md can be told apart from a fresh one."""
    from lazy_harness import __version__
    from lazy_harness.core.sync_agent_md import ROLE_SEGMENT_NAMES, render_agent_md

    out = render_agent_md("head", "common", "tail", names=ROLE_SEGMENT_NAMES)
    assert f"lazy-harness {__version__}" in out


def test_sync_profiles_redeploy_at_same_version_is_byte_identical(tmp_path: Path) -> None:
    """Embedding lh_version must not break idempotence within one version."""
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir)
    _seed_profile(profiles_dir, "lazy")

    sync_profiles(profiles_dir, _adapter())
    first = (profiles_dir / "lazy" / "CLAUDE.md").read_text()

    results = sync_profiles(profiles_dir, _adapter())
    second = (profiles_dir / "lazy" / "CLAUDE.md").read_text()

    assert [r.action for r in results] == ["unchanged"]
    assert first == second


def test_generated_header_names_a_registered_command() -> None:
    """The header tells the reader how to regenerate; it must name a real command."""
    from click import Group

    from lazy_harness.cli.profile_cmd import profile
    from lazy_harness.core.sync_agent_md import GENERATED_HEADER_TMPL

    assert isinstance(profile, Group)
    named = [name for name in profile.commands if f"`lh profile {name}`" in GENERATED_HEADER_TMPL]
    assert named, (
        f"header references no registered subcommand; available: {sorted(profile.commands)}"
    )


def test_sync_profiles_writes_each_profiles_own_system_doc(tmp_path: Path) -> None:
    """The defect (design step 6): `sync_profiles` resolved one adapter above
    its own profile loop.

    The destinations come from `adapter.system_docs()`, so one adapter for the
    whole tree wrote `CLAUDE.md` into a profile running an agent that reads
    `AGENTS.md` — and left the file that agent actually loads unwritten. Its
    caller already resolves per profile (`post_tool_use_sync_system_doc` takes the
    firing profile's adapter), which only moved the defect: whichever profile
    fired the hook imposed its contract file on every other one.
    """
    from lazy_harness.core.config import (
        AgentConfig,
        Config,
        HarnessConfig,
        ProfileEntry,
        ProfilesConfig,
    )
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir)

    _seed_profile(profiles_dir, "lazy")
    work = profiles_dir / "work"
    work.mkdir()
    (work / "head.md").write_text("# head\n")
    (work / "tail.md").write_text("# tail\n")

    cfg = Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type="claude-code"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir="~/.claude-lazy"),
                "work": ProfileEntry(config_dir="~/.codex-work", agent="codex"),
            },
        ),
    )

    sync_profiles(profiles_dir, _adapter(), cfg=cfg)

    assert (profiles_dir / "lazy" / "CLAUDE.md").is_file()
    assert (work / "AGENTS.md").is_file(), (
        f"profile 'work' runs codex; the tree got {sorted(p.name for p in work.iterdir())}"
    )
    assert not (work / "CLAUDE.md").exists()


def test_sync_profiles_writes_nothing_when_the_role_common_is_missing(tmp_path: Path) -> None:
    """The refusal stays ahead of the first write.

    Every profile is preflighted before the first write, so a missing shared
    role segment cannot leave the tree half-synced.
    """
    import pytest

    from lazy_harness.core.config import (
        AgentConfig,
        Config,
        HarnessConfig,
        ProfileEntry,
        ProfilesConfig,
    )
    from lazy_harness.core.sync_agent_md import SyncError, sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "_common").mkdir()

    _seed_profile(profiles_dir, "lazy")
    work = profiles_dir / "work"
    work.mkdir()
    (work / "head.md").write_text("# head\n")
    (work / "tail.md").write_text("# tail\n")

    cfg = Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type="claude-code"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir="~/.claude-lazy"),
                "work": ProfileEntry(config_dir="~/.codex-work", agent="codex"),
            },
        ),
    )

    with pytest.raises(SyncError, match="common.md"):
        sync_profiles(profiles_dir, _adapter(), cfg=cfg)

    assert not (profiles_dir / "lazy" / "CLAUDE.md").exists()


def test_sync_profiles_does_not_demand_a_common_no_profile_uses(tmp_path: Path) -> None:
    """A tree with nothing segmented needs no shared segment.

    The check used to run once, unconditionally, against the single adapter's
    stem — so a flat tree raised about `CLAUDE.common.md` even under a config
    where no profile loads `CLAUDE.md`. Per stem, the file is demanded by the
    profiles that carry segments and by nothing else.
    """
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    flat = profiles_dir / "flat"
    flat.mkdir()
    (flat / "CLAUDE.md").write_text("hand-written\n")

    results = sync_profiles(profiles_dir, _adapter())

    assert [r.action for r in results] == ["skipped"]
    assert (flat / "CLAUDE.md").read_text() == "hand-written\n"


def test_sync_claude_md_command_writes_each_profiles_own_system_doc(tmp_path: Path) -> None:
    """The shipped surface, invoked end to end.

    `sync_profiles` resolves the doc name per directory only when it is handed
    the config. The test above covers that; this one covers the wiring, because
    a command that kept passing one adapter would leave that test green and
    still write `CLAUDE.md` into every profile on the machine.
    """
    import pytest
    from click.testing import CliRunner

    from lazy_harness.cli import profile_cmd

    monkeypatch = pytest.MonkeyPatch()
    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "_common").mkdir(parents=True)
    (profiles_dir / "_common" / "common.md").write_text("# shared\n")

    _seed_profile(profiles_dir, "lazy")
    work = profiles_dir / "work"
    work.mkdir()
    (work / "head.md").write_text("# head\n")
    (work / "tail.md").write_text("# tail\n")

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "lazy"\n\n'
        f'[profiles.lazy]\nconfig_dir = "{tmp_path / "claude-lazy"}"\n\n'
        f'[profiles.work]\nconfig_dir = "{tmp_path / "codex-work"}"\nagent = "codex"\n'
    )
    with monkeypatch.context() as mp:
        mp.setattr(profile_cmd, "config_file", lambda: cfg_file)
        mp.setattr(profile_cmd, "config_dir", lambda: tmp_path)
        result = CliRunner().invoke(profile_cmd.profile, ["sync-claude-md"])

    assert result.exit_code == 0, result.output
    assert (profiles_dir / "lazy" / "CLAUDE.md").is_file()
    assert (work / "AGENTS.md").is_file(), (
        f"profile 'work' runs codex; it got {sorted(p.name for p in work.iterdir())}"
    )
    assert not (work / "CLAUDE.md").exists()


def test_sync_profiles_keeps_the_callers_adapter_for_an_undeclared_directory(
    tmp_path: Path,
) -> None:
    """A leftover directory keeps the caller's answer, not the global default.

    `agent_for_profile` resolves an unknown name to `[agent].type`, so routing
    every directory through it would hand a profile since removed from
    `config.toml` the global agent's doc — which is not what the caller passed
    and not what the directory last held.
    """
    from lazy_harness.core.config import (
        AgentConfig,
        Config,
        HarnessConfig,
        ProfileEntry,
        ProfilesConfig,
    )
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir)
    _seed_profile(profiles_dir, "leftover")

    cfg = Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type="codex"),
        profiles=ProfilesConfig(
            default="work",
            items={"work": ProfileEntry(config_dir="~/.codex-work")},
        ),
    )

    sync_profiles(profiles_dir, _adapter(), cfg=cfg)

    assert (profiles_dir / "leftover" / "CLAUDE.md").is_file()
    assert not (profiles_dir / "leftover" / "AGENTS.md").exists()


def test_one_rendered_document_lands_at_every_destination(tmp_path: Path) -> None:
    """ADR-043 — `system_docs()` is a list of destinations, and the generator
    writes the *identical rendered bytes* to each.

    With a single name the second destination was unreachable: the agent loads
    it, the harness never wrote it, and nothing in the framework could say so.
    """
    from lazy_harness.agents import registry
    from lazy_harness.core.config import (
        AgentConfig,
        Config,
        HarnessConfig,
        ProfileEntry,
        ProfilesConfig,
    )
    from lazy_harness.core.sync_agent_md import sync_profiles

    class _TwoDocs(registry.NullAdapter):
        @property
        def name(self) -> str:
            return "two-docs"

        def system_docs(self) -> list[Path]:
            return [Path("copilot-instructions.md"), Path("instructions/lh.instructions.md")]

    registry._AGENTS["two-docs"] = _TwoDocs
    try:
        profiles_dir = tmp_path / "profiles"
        (profiles_dir / "_common").mkdir(parents=True)
        (profiles_dir / "_common" / "common.md").write_text("# common\n")
        (profiles_dir / "multi").mkdir()
        (profiles_dir / "multi" / "head.md").write_text("# head\n")
        (profiles_dir / "multi" / "tail.md").write_text("# tail\n")

        cfg = Config(
            harness=HarnessConfig(version="1"),
            agent=AgentConfig(type="claude-code"),
            profiles=ProfilesConfig(
                default="multi",
                items={"multi": ProfileEntry(config_dir="~/.multi", agent="two-docs")},
            ),
        )

        sync_profiles(profiles_dir, _adapter(), cfg=cfg)

        first = profiles_dir / "multi" / "copilot-instructions.md"
        second = profiles_dir / "multi" / "instructions" / "lh.instructions.md"
        assert first.is_file()
        assert second.is_file(), (
            "the nested destination was never created; "
            f"tree holds {sorted(p.name for p in (profiles_dir / 'multi').iterdir())}"
        )
        assert first.read_text() == second.read_text()
    finally:
        del registry._AGENTS["two-docs"]


def _seed_role_profile(profiles_dir: Path, name: str, *, head: str, tail: str) -> Path:
    p = profiles_dir / name
    p.mkdir(parents=True)
    (p / "head.md").write_text(head)
    (p / "tail.md").write_text(tail)
    return p


def test_segments_are_named_by_role_not_by_destination_filename(tmp_path: Path) -> None:
    """Decision 4 — the segment tree loses its stem.

    Keying the *source* segments by the *destination* filename forced a
    duplicate tree per agent for identical content, and yields no name at all
    for a destination like `instructions/lh.instructions.md`.
    """
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "_common").mkdir(parents=True)
    (profiles_dir / "_common" / "common.md").write_text("# common rules\n")
    _seed_role_profile(profiles_dir, "lazy", head="# I am lazy\n", tail="# lazy ctx\n")

    results = sync_profiles(profiles_dir, _adapter())

    assert [r.action for r in results] == ["written"]
    out = (profiles_dir / "lazy" / "CLAUDE.md").read_text()
    assert out.index("# I am lazy") < out.index("# common rules") < out.index("# lazy ctx")


def test_the_agent_segment_is_shared_across_profiles_and_lands_after_common(
    tmp_path: Path,
) -> None:
    """`_common/<agent>.md` carries the agent-specific lines once, not once per
    profile: in the deployed tree every such line already lives in the shared
    segment and none in any profile's head or tail."""
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "_common").mkdir(parents=True)
    (profiles_dir / "_common" / "common.md").write_text("# common rules\n")
    (profiles_dir / "_common" / "claude-code.md").write_text("# TaskCreate not TodoWrite\n")
    _seed_role_profile(profiles_dir, "lazy", head="# head\n", tail="# tail\n")
    _seed_role_profile(profiles_dir, "work", head="# head\n", tail="# tail\n")

    sync_profiles(profiles_dir, _adapter())

    for name in ("lazy", "work"):
        out = (profiles_dir / name / "CLAUDE.md").read_text()
        assert (
            out.index("# common rules")
            < out.index("# TaskCreate not TodoWrite")
            < out.index("# tail")
        ), f"profile {name} composed as: {out!r}"


def test_an_agent_with_no_segment_renders_without_one(tmp_path: Path) -> None:
    """The common case, not an error — most agents will never have one."""
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "_common").mkdir(parents=True)
    (profiles_dir / "_common" / "common.md").write_text("# common rules\n")
    _seed_role_profile(profiles_dir, "lazy", head="# head\n", tail="# tail\n")

    results = sync_profiles(profiles_dir, _adapter())

    assert [r.action for r in results] == ["written"]
    assert "claude-code" not in (profiles_dir / "lazy" / "CLAUDE.md").read_text()


def test_the_legacy_stem_keyed_layout_is_skipped_and_named(tmp_path: Path) -> None:
    """A legacy-only tree must not silently keep the retired reader alive."""
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    common = profiles_dir / "_common"
    common.mkdir()
    (common / "CLAUDE.common.md").write_text("# common\n")
    profile = profiles_dir / "lazy"
    profile.mkdir()
    (profile / "CLAUDE.head.md").write_text("# head\n")
    (profile / "CLAUDE.tail.md").write_text("# tail\n")

    results = sync_profiles(profiles_dir, _adapter())

    assert [r.action for r in results] == ["skipped"]
    assert "CLAUDE.head.md" in results[0].reason
    assert "lh profile migrate lazy" in results[0].reason
    assert not (profiles_dir / "lazy" / "CLAUDE.md").exists()


def test_the_role_layout_wins_over_a_legacy_layout_left_beside_it(tmp_path: Path) -> None:
    """Mid-migration a tree carries both. The role names are the answer, and
    the legacy files are leftovers — reading them would make the rename a
    no-op that reports success."""
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "_common").mkdir(parents=True)
    (profiles_dir / "_common" / "common.md").write_text("# new common\n")
    (profiles_dir / "_common" / "CLAUDE.common.md").write_text("# old common\n")
    p = _seed_role_profile(profiles_dir, "lazy", head="# new head\n", tail="# new tail\n")
    (p / "CLAUDE.head.md").write_text("# LEGACY MARKER\n")
    (p / "CLAUDE.tail.md").write_text("# old tail\n")

    sync_profiles(profiles_dir, _adapter())

    out = (p / "CLAUDE.md").read_text()
    assert "# new head" in out
    assert "# LEGACY MARKER" not in out


def test_segment_filenames_is_derived_from_the_registry(tmp_path: Path) -> None:
    """Decision 5's gate: the sync hook's trigger set is computed from the
    segment roles, not listed. A static list is how a renamed segment stops
    firing the hook that regenerates it — silently, in the one file whose
    purpose is to be authoritative."""
    from lazy_harness.agents.registry import get_agent, list_agents
    from lazy_harness.core.sync_agent_md import segment_filenames

    names = segment_filenames()

    assert {"head.md", "tail.md", "common.md"} <= names
    for agent_type in list_agents():
        docs = get_agent(agent_type).system_docs()
        if not docs:
            continue
        assert f"{agent_type}.md" in names, f"{agent_type} has no agent segment name"
    assert "CLAUDE.head.md" not in names
    assert "CLAUDE.tail.md" not in names
    assert "CLAUDE.common.md" not in names


def test_sync_profiles_only_walks_the_named_profile(tmp_path: Path) -> None:
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir)
    _seed_profile(profiles_dir, "lazy")
    _seed_profile(profiles_dir, "flex")

    results = sync_profiles(profiles_dir, _adapter(), only="flex")

    assert {r.profile for r in results} == {"flex"}
    assert not (profiles_dir / "lazy" / "CLAUDE.md").exists()


def test_one_agents_segment_never_reaches_another_agents_document(tmp_path: Path) -> None:
    """`_common/<agent>.md` is keyed by the agent the *profile* runs.

    A shared `_common/` directory holds one segment per agent, so the isolation
    is the whole point of the name: a Codex worker that read Claude Code's
    segment would be told to call `TaskCreate`, which its harness does not
    deliver. The tree is the deployed shape — one `_common/`, profiles running
    different agents beside each other.
    """
    from lazy_harness.core.config import (
        AgentConfig,
        Config,
        HarnessConfig,
        ProfileEntry,
        ProfilesConfig,
    )
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "_common").mkdir(parents=True)
    (profiles_dir / "_common" / "common.md").write_text("# shared rules\n")
    (profiles_dir / "_common" / "claude-code.md").write_text("# claude-code only\n")
    (profiles_dir / "_common" / "codex.md").write_text("# codex only\n")
    _seed_role_profile(profiles_dir, "lazy", head="# lazy id\n", tail="# lazy ctx\n")
    _seed_role_profile(profiles_dir, "lazy-codex", head="# codex id\n", tail="# codex ctx\n")

    cfg = Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type="claude-code"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir="~/.claude-lazy"),
                "lazy-codex": ProfileEntry(config_dir="~/.codex-lazy", agent="codex"),
            },
        ),
    )

    sync_profiles(profiles_dir, _adapter(), cfg=cfg)

    codex_doc = (profiles_dir / "lazy-codex" / "AGENTS.md").read_text()
    assert "# codex only" in codex_doc
    assert "# claude-code only" not in codex_doc, (
        "Claude Code's agent segment reached a Codex document"
    )

    claude_doc = (profiles_dir / "lazy" / "CLAUDE.md").read_text()
    assert "# claude-code only" in claude_doc
    assert "# codex only" not in claude_doc, "Codex's agent segment reached a Claude Code document"


def test_the_codex_document_is_composed_head_common_codex_tail(tmp_path: Path) -> None:
    """The order ADR-043 §2 names, asserted for the agent this wave wires up.

    The existing order test runs against Claude Code. Codex is the first agent
    whose destination is not `CLAUDE.md`, so its document is assembled through
    the per-profile destination resolution as well as the composition — one
    test that both halves agree.
    """
    from lazy_harness.core.config import (
        AgentConfig,
        Config,
        HarnessConfig,
        ProfileEntry,
        ProfilesConfig,
    )
    from lazy_harness.core.sync_agent_md import sync_profiles

    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "_common").mkdir(parents=True)
    (profiles_dir / "_common" / "common.md").write_text("# shared rules\n")
    (profiles_dir / "_common" / "codex.md").write_text("# codex rules\n")
    _seed_role_profile(profiles_dir, "lazy-codex", head="# codex id\n", tail="# codex ctx\n")

    cfg = Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type="claude-code"),
        profiles=ProfilesConfig(
            default="lazy-codex",
            items={"lazy-codex": ProfileEntry(config_dir="~/.codex-lazy", agent="codex")},
        ),
    )

    results = sync_profiles(profiles_dir, _adapter(), cfg=cfg)

    assert [r.action for r in results] == ["written"]
    assert not (profiles_dir / "lazy-codex" / "CLAUDE.md").exists()
    out = (profiles_dir / "lazy-codex" / "AGENTS.md").read_text()
    assert (
        out.index("# codex id")
        < out.index("# shared rules")
        < out.index("# codex rules")
        < out.index("# codex ctx")
    ), f"composed as: {out!r}"
    header = out.splitlines()[0]
    assert "_common/codex.md" in header, (
        f"the header must name the agent segment a reader should edit: {header!r}"
    )
