"""The mtime/size abort — decision 4's answer to a deploy racing a live agent.

Atomic replace prevents a half-written file; it does not prevent losing an
approval the agent wrote *after* the engine read the document. Both Codex and
Copilot were observed writing their own config mid-session, so the engine
records each target's mtime and size at read time and refuses the whole plan if
any of them moved before apply.

These tests pin the refusal, not the merge: every one of them drives the real
`deploy_config` and asserts on the filesystem afterwards, because an exception
raised before a write and an exception raised after one look identical from the
call site.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
)


def _cfg(profile_dir: Path, *, name: str = "personal") -> Config:
    return Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default=name,
            items={name: ProfileEntry(config_dir=str(profile_dir))},
        ),
        hooks={},
    )


@pytest.fixture
def servers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin MCP discovery, which otherwise probes the developer's machine."""
    from lazy_harness.deploy import engine

    monkeypatch.setattr(
        engine,
        "_collect_mcp_servers",
        lambda cfg: {"qmd": {"command": "qmd", "args": ["mcp"]}},
    )


def _touch_during_plan(
    monkeypatch: pytest.MonkeyPatch, profile_dir: Path, name: str, content: str
) -> None:
    """Have the agent write `name` while the plan is being produced.

    Patching `plan_config` is how a live agent is simulated without one: the
    engine has already read and stat'd its targets by the time the planner is
    called, so a write from inside it lands in exactly the window the abort
    exists to close.
    """
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    original = ClaudeCodeAdapter.plan_config

    def planning(self, hooks, servers, existing, **kw):  # type: ignore[no-untyped-def]
        (profile_dir / name).write_text(content)
        return original(self, hooks, servers, existing, **kw)

    monkeypatch.setattr(ClaudeCodeAdapter, "plan_config", planning)


def test_a_target_growing_between_read_and_apply_aborts_the_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: None
) -> None:
    """Size alone is enough: the agent appended something the plan never saw."""
    from lazy_harness.deploy.engine import ConfigTargetChangedError, deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "settings.json").write_text('{"model": "opus"}\n')

    _touch_during_plan(
        monkeypatch, profile_dir, "settings.json", '{"model": "opus", "theme": "dark"}\n'
    )

    with pytest.raises(ConfigTargetChangedError):
        deploy_config(_cfg(profile_dir))


def test_a_target_rewritten_to_the_same_size_still_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: None
) -> None:
    """mtime alone is enough, so neither half of the pair is decoration.

    The replacement is byte-length-identical on purpose: with only `st_size`
    compared this deploy would sail through and overwrite the edit.
    """
    from lazy_harness.deploy.engine import ConfigTargetChangedError, deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    settings = profile_dir / "settings.json"
    settings.write_text('{"model": "opus"}\n')

    _touch_during_plan(monkeypatch, profile_dir, "settings.json", '{"model": "sonn"}\n')

    with pytest.raises(ConfigTargetChangedError):
        deploy_config(_cfg(profile_dir))

    assert len(settings.read_text()) == len('{"model": "opus"}\n')


def test_a_target_that_appears_after_the_read_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: None
) -> None:
    """Absent-then-present is a change too.

    The read pass skips a target that does not exist, so without this the very
    first file an agent creates mid-deploy is the one the engine is guaranteed
    to clobber — it planned against no prior content at all.
    """
    from lazy_harness.deploy.engine import ConfigTargetChangedError, deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()

    _touch_during_plan(monkeypatch, profile_dir, ".claude.json", '{"mcpServers": {"mine": {}}}\n')

    with pytest.raises(ConfigTargetChangedError):
        deploy_config(_cfg(profile_dir))

    assert '"mine"' in (profile_dir / ".claude.json").read_text()


def test_the_abort_writes_nothing_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: None
) -> None:
    """The whole plan is refused, not the one op whose target moved.

    `settings.json` and `.claude.json` are planned in one call; a check done
    inside `_apply` would write the first before discovering the second.
    """
    from lazy_harness.deploy.engine import ConfigTargetChangedError, deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "settings.json").write_text('{"model": "opus"}\n')
    (profile_dir / ".claude.json").write_text('{"mcpServers": {}}\n')

    _touch_during_plan(monkeypatch, profile_dir, ".claude.json", '{"mcpServers": {"mine": {}}}\n')

    with pytest.raises(ConfigTargetChangedError):
        deploy_config(_cfg(profile_dir))

    assert (profile_dir / "settings.json").read_text() == '{"model": "opus"}\n'
    assert not (profile_dir / "settings.json.bak").exists()


def test_the_refusal_names_the_profile_and_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: None
) -> None:
    """A refusal the operator cannot act on is the silence this design refuses."""
    from lazy_harness.deploy.engine import ConfigTargetChangedError, deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "settings.json").write_text('{"model": "opus"}\n')

    _touch_during_plan(monkeypatch, profile_dir, "settings.json", '{"model": "opus", "a": 1}\n')

    with pytest.raises(ConfigTargetChangedError) as caught:
        deploy_config(_cfg(profile_dir, name="work"))

    message = str(caught.value)
    assert "work" in message
    assert "settings.json" in message
    assert caught.value.profile == "work"
    assert caught.value.changed == [Path("settings.json")]


def test_an_untouched_deploy_still_writes(tmp_path: Path, servers: None) -> None:
    """The guard is a refusal on change, not a refusal on every second deploy.

    Deploying twice in a row is the ordinary case: the second read sees what the
    first wrote, so the recorded stat and the pre-apply stat agree.
    """
    from lazy_harness.deploy.engine import deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()

    deploy_config(_cfg(profile_dir))
    first = (profile_dir / "settings.json").read_text()

    deploy_config(_cfg(profile_dir))

    assert (profile_dir / "settings.json").read_text() == first


def test_a_stat_recorded_with_a_coarse_clock_still_catches_a_same_second_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: None
) -> None:
    """Two writes inside one filesystem timestamp tick must not look identical.

    `os.utime` forces the post-plan mtime back to the pre-plan one, which is what
    a one-second-resolution filesystem would have produced on its own. Size is
    the half that has to carry it here.
    """
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.deploy.engine import ConfigTargetChangedError, deploy_config

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    settings = profile_dir / "settings.json"
    settings.write_text('{"model": "opus"}\n')
    frozen = settings.stat()

    original = ClaudeCodeAdapter.plan_config

    def planning(self, hooks, servers, existing, **kw):  # type: ignore[no-untyped-def]
        settings.write_text('{"model": "opus", "theme": "dark"}\n')
        os.utime(settings, ns=(frozen.st_atime_ns, frozen.st_mtime_ns))
        return original(self, hooks, servers, existing, **kw)

    monkeypatch.setattr(ClaudeCodeAdapter, "plan_config", planning)

    with pytest.raises(ConfigTargetChangedError):
        deploy_config(_cfg(profile_dir))
