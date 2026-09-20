"""The config deploy cycle — discover, read, plan, apply.

Merging is the adapter's (decision 4, 2026-09-13 multi-agent design); the engine
only does I/O. These tests pin the engine half: that it asks for the targets,
reads the ones that exist, applies exactly one deploy plan per profile, and
refuses an adapter that cannot plan at all. The MCP gap diagnostic also compares
two fresh, unapplied plans with and without servers.

Byte identity with the writers this replaces is pinned in `tests/goldens/config-
deploy/`, captured from the engine as it wrote before the merge logic moved.
Comparing against the adapter instead would compare the new code with itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness import __version__
from lazy_harness.agents.base import ConfigArtifact, WriteOp
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
)

GOLDENS = Path(__file__).parent.parent / "goldens" / "config-deploy"

MCP_SERVERS: dict[str, dict] = {
    "qmd": {"command": "qmd", "args": ["mcp"]},
    "engram": {"command": "engram", "args": ["mcp", "serve"], "env": {"ENGRAM_DB": "/tmp/e.db"}},
}


def _golden(name: str) -> str:
    """A golden document, with the captured version replaced by the running one.

    `lh_version` is the one field that legitimately changes between the capture
    and the run; everything else — key order, indentation, the trailing newline —
    is compared byte for byte, because a chezmoi-managed profile diffs on it.
    """
    return GOLDENS.joinpath(name).read_text().replace("@VERSION@", __version__)


def _cfg(profile_dir: Path, *, name: str = "personal") -> Config:
    return Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default=name,
            items={name: ProfileEntry(config_dir=str(profile_dir))},
        ),
        hooks={},
    )


def _two_profiles(home: Path) -> Config:
    return Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir=str(home / ".claude-lazy")),
                "flex": ProfileEntry(config_dir=str(home / ".claude-flex")),
            },
        ),
        hooks={},
    )


@pytest.fixture
def servers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin MCP discovery, which otherwise probes the developer's machine."""
    from lazy_harness.deploy import engine

    monkeypatch.setattr(engine, "_collect_mcp_servers", lambda cfg: dict(MCP_SERVERS))


@pytest.fixture
def seeded_profile(tmp_path: Path) -> Path:
    """A profile carrying the documents the goldens were captured against."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "settings.json").write_text(_golden("existing-settings.json"))
    (profile_dir / ".claude.json").write_text(_golden("existing-claude.json"))
    return profile_dir


# --- byte identity, against the engine as it wrote before the move -------


def test_settings_bytes_match_the_golden(seeded_profile: Path, servers: None) -> None:
    from lazy_harness.deploy.engine import deploy_config

    deploy_config(_cfg(seeded_profile))

    assert (seeded_profile / "settings.json").read_text() == _golden("settings.json")


def test_mcp_bytes_match_the_golden(seeded_profile: Path, servers: None) -> None:
    from lazy_harness.deploy.engine import deploy_config

    deploy_config(_cfg(seeded_profile))

    assert (seeded_profile / ".claude.json").read_text() == _golden("claude.json")


def test_a_second_deploy_changes_no_bytes(seeded_profile: Path, servers: None) -> None:
    """Idempotence is what makes a chezmoi-managed profile converge."""
    from lazy_harness.deploy.engine import deploy_config

    deploy_config(_cfg(seeded_profile))
    first = {
        "settings.json": (seeded_profile / "settings.json").read_text(),
        ".claude.json": (seeded_profile / ".claude.json").read_text(),
    }

    deploy_config(_cfg(seeded_profile))

    for name, before in first.items():
        assert (seeded_profile / name).read_text() == before, f"{name} changed on redeploy"


# --- the cycle -----------------------------------------------------------


def test_one_deploy_plan_per_profile_is_applied_beside_fresh_mcp_diagnostics(
    tmp_path: Path, servers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the plan carrying hooks is applied for each profile.

    The two additional fresh plans are the MCP gap diagnostic's differential;
    neither reaches `_apply`, so an adapter whose hooks and MCP share a file
    still emits one deploy plan and cannot overwrite its own earlier result.
    """
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.deploy.engine import deploy_config

    calls: list[tuple[bool, bool, bool]] = []
    original = ClaudeCodeAdapter.plan_config

    def counting(self, hooks, servers_arg, existing, **kwargs):
        calls.append((bool(hooks), bool(servers_arg), bool(existing)))
        return original(self, hooks, servers_arg, existing, **kwargs)

    monkeypatch.setattr(ClaudeCodeAdapter, "plan_config", counting)

    deploy_config(_two_profiles(tmp_path))

    assert len(calls) == 6
    assert calls.count((True, True, False)) == 2
    assert calls.count((False, True, False)) == 2
    assert calls.count((False, False, False)) == 2


def test_only_existing_targets_are_read(tmp_path: Path, servers: None) -> None:
    """A target that is not on disk must arrive absent, not as an empty string —
    the adapter distinguishes them."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.deploy.engine import deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "settings.json").write_text('{"model": "opus"}\n')

    seen: dict[Path, str] = {}
    original = ClaudeCodeAdapter.plan_config

    def capturing(self, hooks, servers_arg, existing, **kwargs):
        seen.update(existing)
        return original(self, hooks, servers_arg, existing, **kwargs)

    ClaudeCodeAdapter.plan_config = capturing  # type: ignore[method-assign]
    try:
        deploy_config(_cfg(profile_dir))
    finally:
        ClaudeCodeAdapter.plan_config = original  # type: ignore[method-assign]

    assert list(seen) == [Path("settings.json")]
    assert seen[Path("settings.json")] == '{"model": "opus"}\n'


def test_a_plan_that_deletes_removes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`artifact is None` is how an adapter retires a file it used to generate."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.deploy.engine import deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "settings.json").write_text("{}\n")

    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "plan_config",
        lambda self, hooks, servers, existing, **kw: [
            WriteOp(artifact=None, relative_path=Path("settings.json"))
        ],
    )

    deploy_config(_cfg(profile_dir))

    assert not (profile_dir / "settings.json").exists()


def test_a_delete_of_a_file_that_is_not_there_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.deploy.engine import deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()

    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "plan_config",
        lambda self, hooks, servers, existing, **kw: [
            WriteOp(artifact=None, relative_path=Path("settings.json"))
        ],
    )

    deploy_config(_cfg(profile_dir))  # must not raise


def test_narrowing_still_decides_which_profiles_are_touched(tmp_path: Path, servers: None) -> None:
    from lazy_harness.deploy.engine import deploy_config

    deploy_config(_two_profiles(tmp_path), only="flex")

    assert (tmp_path / ".claude-flex" / "settings.json").is_file()
    assert not (tmp_path / ".claude-lazy").exists()


def test_an_unknown_profile_is_refused(tmp_path: Path, servers: None) -> None:
    from lazy_harness.deploy.engine import UnknownProfileError, deploy_config

    with pytest.raises(UnknownProfileError, match="tmp-gate"):
        deploy_config(_two_profiles(tmp_path), only="tmp-gate")


# --- an adapter that cannot plan config ----------------------------------


class _PlannerlessAdapter:
    """Everything the deploy needs except the ConfigPlanner half."""

    @property
    def name(self) -> str:
        return "plannerless"

    def config_dir_env_var(self) -> str:
        return "PLANNERLESS_CONFIG_DIR"

    def mcp_config_file(self) -> str:
        return ".plannerless.json"

    def global_config_link(self) -> Path | None:
        return None


def test_an_adapter_without_config_planner_is_refused(
    tmp_path: Path, servers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Protocol's own docstring: refused up front, not discovered mid-deploy."""
    from lazy_harness.deploy import engine

    monkeypatch.setattr(engine, "agent_for_profile", lambda cfg, name: _PlannerlessAdapter())

    with pytest.raises(engine.ConfigPlannerRequiredError, match="plannerless"):
        engine.deploy_config(_cfg(tmp_path / "profile"))


def test_a_refused_adapter_writes_nothing_at_all(
    tmp_path: Path, servers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Up front means before the first profile is written, not after it."""
    from lazy_harness.deploy import engine

    home = tmp_path
    cfg = _two_profiles(home)

    def planner_for(_cfg_arg: Config, name: str) -> object:
        # `lazy` can plan; `flex` cannot. Iterating and writing as it goes would
        # leave `lazy` deployed against a run that must not have started.
        from lazy_harness.agents.registry import get_agent

        return get_agent("claude-code") if name == "lazy" else _PlannerlessAdapter()

    monkeypatch.setattr(engine, "agent_for_profile", planner_for)

    with pytest.raises(engine.ConfigPlannerRequiredError):
        engine.deploy_config(cfg)

    assert not (home / ".claude-lazy").exists()
    assert not (home / ".claude-flex").exists()


def test_the_refusal_names_the_adapter_and_the_profile(
    tmp_path: Path, servers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    monkeypatch.setattr(engine, "agent_for_profile", lambda cfg, name: _PlannerlessAdapter())

    with pytest.raises(engine.ConfigPlannerRequiredError) as excinfo:
        engine.deploy_config(_cfg(tmp_path / "profile", name="beta"))

    message = str(excinfo.value)
    assert "beta" in message
    assert "plannerless" in message


def test_the_refusal_reads_name_the_way_the_protocol_declares_it(
    tmp_path: Path, servers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`AgentAdapter.name` is a property, so the refusal reads it, never calls it.

    Anchored on the shipped `NullAdapter` rather than a fake this module shapes:
    a fake that declares `name()` as a method matches a buggy call site and
    reports the refusal as green while the real adapters raise `TypeError`.
    """
    from lazy_harness.agents.registry import NullAdapter
    from lazy_harness.deploy import engine

    monkeypatch.setattr(engine, "agent_for_profile", lambda cfg, name: NullAdapter())

    with pytest.raises(engine.ConfigPlannerRequiredError) as excinfo:
        engine.deploy_config(_cfg(tmp_path / "profile", name="beta"))

    assert excinfo.value.agent_name == "null"
    assert excinfo.value.profile == "beta"


# --- the deploy report ---------------------------------------------------


def test_preserved_entries_are_reported(
    seeded_profile: Path, servers: None, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.deploy.engine import deploy_config

    deploy_config(_cfg(seeded_profile))

    out = capsys.readouterr().out
    assert "preserved 3" in out
    assert "other-tool guard" in out
    assert "notifier send" in out


def test_repaired_entries_are_reported(
    seeded_profile: Path, servers: None, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.deploy.engine import deploy_config

    deploy_config(_cfg(seeded_profile))

    out = capsys.readouterr().out
    assert "repaired 1" in out
    assert 'matcher: null -> ""' in out


def test_a_repair_leaves_a_backup_of_what_was_there(seeded_profile: Path, servers: None) -> None:
    """The backup is I/O, so it is the engine's — the adapter only reports."""
    from lazy_harness.deploy.engine import deploy_config

    before = (seeded_profile / "settings.json").read_text()

    deploy_config(_cfg(seeded_profile))

    assert (seeded_profile / "settings.json.bak").read_text() == before


def test_no_backup_is_written_when_nothing_was_repaired(tmp_path: Path, servers: None) -> None:
    from lazy_harness.deploy.engine import deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()

    deploy_config(_cfg(profile_dir))

    assert not (profile_dir / "settings.json.bak").exists()


def test_dropped_entries_are_reported(
    seeded_profile: Path, servers: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """A builtin retired from a release leaves its command behind in every
    profile; pruning it is the one thing the merge does that is otherwise
    invisible."""
    from lazy_harness.deploy.engine import deploy_config

    deploy_config(_cfg(seeded_profile))

    out = capsys.readouterr().out
    assert "dropped 1" in out
    assert "post-tool-use-sync-claude" in out


def test_a_long_reported_command_is_truncated_by_the_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Column width and truncation are the engine's; the adapter emits flat
    strings and knows nothing about a terminal."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.deploy.engine import deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    long_command = "other-tool " + "x" * 200

    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "plan_config",
        lambda self, hooks, servers, existing, **kw: [
            WriteOp(
                artifact=ConfigArtifact(relative_path=Path("settings.json"), content="{}\n"),
                relative_path=Path("settings.json"),
                preserved=[f"PreToolUse: {long_command}"],
            )
        ],
    )

    deploy_config(_cfg(profile_dir))

    out = capsys.readouterr().out
    assert long_command not in out, "the engine printed an untruncated command"
    assert "other-tool xxx" in out


# --- what the move deletes ----------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "_merge_hook_blocks",
        "_is_harness_owned",
        "_normalize_entry",
        "_owned_binaries",
        "_entry_commands",
    ],
)
def test_the_engine_no_longer_carries_its_own_merge_logic(name: str) -> None:
    """Two copies of one merge is the defect this step removes. The surviving
    copy is `agents/claude_code.py`."""
    from lazy_harness.agents import claude_code
    from lazy_harness.deploy import engine

    assert not hasattr(engine, name), f"deploy/engine.py still defines {name}"
    assert hasattr(claude_code, name), f"{name} is not on the adapter either"


def test_the_engine_does_not_serialise_json_for_a_config_target(
    seeded_profile: Path, servers: None
) -> None:
    """Writing final text is the engine's job; producing it is not. A `json.dumps`
    of a config document in the engine means the merge came back."""
    import inspect

    from lazy_harness.deploy import engine

    source = inspect.getsource(engine)
    assert "json.dumps" not in source, "deploy/engine.py is serialising config again"


def test_the_written_bytes_are_exactly_what_the_plan_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The engine writes the artifact's content verbatim — no reserialising, no
    trailing-newline fixups of its own."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.deploy.engine import deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    content = '{"deliberately":   "odd spacing"}no trailing newline'

    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "plan_config",
        lambda self, hooks, servers, existing, **kw: [
            WriteOp(
                artifact=ConfigArtifact(relative_path=Path("settings.json"), content=content),
                relative_path=Path("settings.json"),
            )
        ],
    )

    deploy_config(_cfg(profile_dir))

    assert (profile_dir / "settings.json").read_text() == content


def test_a_profile_without_a_config_dir_yet_gets_one(tmp_path: Path, servers: None) -> None:
    from lazy_harness.deploy.engine import deploy_config

    profile_dir = tmp_path / "not-created-yet"

    deploy_config(_cfg(profile_dir))

    assert (profile_dir / "settings.json").is_file()
    assert json.loads((profile_dir / "settings.json").read_text())["hooks"]


# --- deletes, in both directions ------------------------------------------


def test_one_plan_deletes_one_file_and_writes_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The delete gate, both directions in a single plan.

    Asserting the removal alone would pass on an engine that unlinked every path
    it was handed; asserting the write alone would pass on one that never
    deleted at all. The file the plan does not name is the third direction: a
    deploy that swept the config dir would take it too.
    """
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.deploy.engine import deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "settings.json").write_text('{"retired": true}\n')
    (profile_dir / ".claude.json").write_text('{"stale": true}\n')
    (profile_dir / "CLAUDE.md").write_text("# not a config target\n")

    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "plan_config",
        lambda self, hooks, servers, existing, **kw: [
            WriteOp(artifact=None, relative_path=Path("settings.json")),
            WriteOp(
                artifact=ConfigArtifact(
                    relative_path=Path(".claude.json"), content='{"fresh": true}\n'
                ),
                relative_path=Path(".claude.json"),
            ),
        ],
    )

    deploy_config(_cfg(profile_dir))

    assert not (profile_dir / "settings.json").exists(), "the retired file survived"
    assert (profile_dir / ".claude.json").read_text() == '{"fresh": true}\n'
    assert (profile_dir / "CLAUDE.md").read_text() == "# not a config target\n"


def test_a_delete_is_reported_so_a_removal_is_never_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.deploy.engine import deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "settings.json").write_text("{}\n")

    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "plan_config",
        lambda self, hooks, servers, existing, **kw: [
            WriteOp(artifact=None, relative_path=Path("settings.json"))
        ],
    )

    deploy_config(_cfg(profile_dir))

    assert "settings.json" in capsys.readouterr().out
