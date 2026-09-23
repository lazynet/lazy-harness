"""Tests for the lh deploy CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Hooks and MCP servers are one step since the ConfigPlanner move: they are
# planned together so an adapter whose documents overlap writes each once.
STEPS = (
    ("profiles", "deploy_profiles"),
    ("config", "deploy_config"),
    ("symlink", "deploy_claude_symlink"),
    ("plugins", "repair_plugin_registries"),
)


@pytest.mark.parametrize("args", [[], ["--profile", "one"]])
def test_deploy_reports_corrupt_skill_ledger_before_snapshot_or_writes(
    home_dir: Path, args: list[str]
) -> None:
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli
    from lazy_harness.core.config import Config, ProfileEntry, save_config
    from lazy_harness.core.paths import config_dir, config_file
    from lazy_harness.deploy.skills import SKILL_LEDGER_RELATIVE

    cfg = Config()
    cfg.profiles.default = "one"
    cfg.profiles.items = {"one": ProfileEntry(config_dir=str(home_dir / ".one"), agent="codex")}
    save_config(cfg, config_file())
    source = config_dir() / "profiles" / "one" / "shared" / "skills" / "portable"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("body")
    ledger = home_dir / ".agents" / SKILL_LEDGER_RELATIVE
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{broken")

    result = CliRunner().invoke(cli, ["deploy", *args])

    assert result.exit_code == 1
    assert "Error:" in result.output
    assert str(ledger) in result.output
    assert "Restore" in result.output
    assert "Snapshot:" not in result.output
    assert not (home_dir / ".one").exists()
    assert not (home_dir / ".agents" / "skills").exists()
    assert ledger.read_text() == "{broken"


def _record_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Replace each deploy step with a recorder of the `only` it received."""
    from lazy_harness.cli import deploy_cmd

    seen: dict[str, object] = {}

    def recorder(step: str):
        # `**_` absorbs the hand-off between steps: `deploy_profiles` returns the
        # config targets it displaced and `deploy_config` takes them. What this
        # helper pins is which steps run and how they are narrowed, so the empty
        # mapping stands in for both halves of that.
        def _call(cfg, *, only=None, **_) -> dict:
            seen[step] = only
            return {}

        return _call

    for step, attr in STEPS:
        monkeypatch.setattr(deploy_cmd, attr, recorder(step))
    monkeypatch.setattr(deploy_cmd, "_sync_system_docs", recorder("sync"))
    return seen


def test_run_deploy_invokes_every_step(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core.config import Config

    seen = _record_calls(monkeypatch)

    deploy_cmd._run_deploy(Config())

    assert set(seen) == {"sync", *(step for step, _ in STEPS)}


def test_run_deploy_without_a_profile_narrows_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the no-flag path still reaches every step unnarrowed."""
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core.config import Config

    seen = _record_calls(monkeypatch)

    deploy_cmd._run_deploy(Config())

    assert list(seen.values()) == [None] * (len(STEPS) + 1)


def test_run_deploy_forwards_the_named_profile_to_every_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A step that dropped `only` would deploy every profile from a narrowed run."""
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core.config import Config

    seen = _record_calls(monkeypatch)

    deploy_cmd._run_deploy(Config(), "flex")

    assert list(seen.values()) == ["flex"] * (len(STEPS) + 1)


def test_sync_runs_before_profiles_are_deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core.config import Config

    calls: list[str] = []
    monkeypatch.setattr(
        deploy_cmd, "_sync_system_docs", lambda cfg, *, only=None: calls.append("sync")
    )
    monkeypatch.setattr(
        deploy_cmd, "deploy_profiles", lambda cfg, *, only=None: calls.append("profiles")
    )
    monkeypatch.setattr(deploy_cmd, "deploy_config", lambda cfg, *, only=None, displaced=None: None)
    monkeypatch.setattr(deploy_cmd, "deploy_claude_symlink", lambda cfg, *, only=None: None)

    deploy_cmd._run_deploy(Config())

    assert calls == ["sync", "profiles"]


def test_sync_error_stops_deploy(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core.config import Config
    from lazy_harness.core.sync_agent_md import SyncError

    monkeypatch.setattr(
        deploy_cmd,
        "_sync_system_docs",
        MagicMock(side_effect=SyncError("missing common.md")),
    )
    deploy = MagicMock()
    monkeypatch.setattr(deploy_cmd, "deploy_profiles", deploy)

    with pytest.raises(SystemExit) as exc:
        deploy_cmd._run_deploy(Config())

    assert exc.value.code == 1
    deploy.assert_not_called()


def test_deploy_sync_restamps_the_assembled_document(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core import sync_agent_md
    from lazy_harness.core.config import Config, HarnessConfig, ProfileEntry, ProfilesConfig
    from lazy_harness.core.paths import config_dir

    profiles = config_dir() / "profiles"
    (profiles / "_common").mkdir(parents=True)
    (profiles / "_common" / "common.md").write_text("common\n")
    profile = profiles / "lazy"
    profile.mkdir()
    (profile / "head.md").write_text("head\n")
    (profile / "tail.md").write_text("tail\n")
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={"lazy": ProfileEntry(config_dir=str(home_dir / "agent"))},
        ),
    )
    seen: list[str] = []
    monkeypatch.setattr(
        deploy_cmd,
        "deploy_profiles",
        lambda cfg, *, only=None: seen.append((profile / "CLAUDE.md").read_text()),
    )
    monkeypatch.setattr(deploy_cmd, "deploy_config", lambda cfg, *, only=None, displaced=None: None)
    monkeypatch.setattr(deploy_cmd, "deploy_claude_symlink", lambda cfg, *, only=None: None)

    monkeypatch.setattr(sync_agent_md, "__version__", "1.0.0")
    deploy_cmd._run_deploy(cfg)
    monkeypatch.setattr(sync_agent_md, "__version__", "2.0.0")
    deploy_cmd._run_deploy(cfg)

    assert "GENERATED by `lh profile sync-system-doc` (lazy-harness 1.0.0)" in seen[0]
    assert "GENERATED by `lh profile sync-system-doc` (lazy-harness 2.0.0)" in seen[1]


def test_hooks_and_mcp_are_one_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI must not call the two halves separately: that is two plans per
    profile, and an adapter whose documents overlap would overwrite its own
    first result."""
    from lazy_harness.cli import deploy_cmd

    assert not hasattr(deploy_cmd, "deploy_hooks")
    assert not hasattr(deploy_cmd, "deploy_mcp_servers")


def test_an_adapter_that_cannot_plan_config_exits_nonzero(
    home_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused with a message, not a traceback."""
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli
    from lazy_harness.core.config import (
        Config,
        HarnessConfig,
        ProfileEntry,
        ProfilesConfig,
        save_config,
    )
    from lazy_harness.core.paths import config_dir
    from lazy_harness.deploy import engine

    save_config(
        Config(
            harness=HarnessConfig(version="1"),
            profiles=ProfilesConfig(
                default="lazy",
                items={"lazy": ProfileEntry(config_dir=str(home_dir / ".claude-lazy"))},
            ),
        ),
        config_dir() / "config.toml",
    )

    class _Plannerless:
        @property
        def name(self) -> str:
            return "plannerless"

        def mcp_config_file(self) -> str:
            return ".plannerless.json"

        def global_config_link(self):
            return None

        def default_home(self):
            return Path.home() / ".fake"

    monkeypatch.setattr(engine, "agent_for_profile", lambda cfg, name: _Plannerless())

    result = CliRunner().invoke(cli, ["deploy"])

    assert result.exit_code != 0
    assert "plannerless" in result.output
    assert "Traceback" not in result.output


def test_a_skill_collision_exits_nonzero_without_a_traceback(home_dir: Path) -> None:
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli
    from lazy_harness.core.config import Config, ProfileEntry, save_config
    from lazy_harness.core.paths import config_dir

    profiles = config_dir() / "profiles"
    for name, body in (("one", "one"), ("two", "two")):
        skill = profiles / name / "codex" / "skills" / "same"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(body)
    cfg = Config()
    cfg.profiles.default = "one"
    cfg.profiles.items = {
        name: ProfileEntry(config_dir=str(home_dir / f".{name}"), agent="codex")
        for name in ("one", "two")
    }
    save_config(cfg, config_dir() / "config.toml")

    result = CliRunner().invoke(cli, ["deploy"])

    assert result.exit_code != 0
    assert "same" in result.output
    assert "different content" in result.output
    assert "Traceback" not in result.output
