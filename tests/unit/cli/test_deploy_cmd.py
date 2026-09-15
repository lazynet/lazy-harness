"""Tests for the lh deploy CLI command."""

from __future__ import annotations

import pytest

# Hooks and MCP servers are one step since the ConfigPlanner move: they are
# planned together so an adapter whose documents overlap writes each once.
STEPS = (
    ("profiles", "deploy_profiles"),
    ("config", "deploy_config"),
    ("symlink", "deploy_claude_symlink"),
)


def _record_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Replace each deploy step with a recorder of the `only` it received."""
    from lazy_harness.cli import deploy_cmd

    seen: dict[str, object] = {}

    def recorder(step: str):
        def _call(cfg, *, only=None) -> None:
            seen[step] = only

        return _call

    for step, attr in STEPS:
        monkeypatch.setattr(deploy_cmd, attr, recorder(step))
    return seen


def test_run_deploy_invokes_every_step(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core.config import Config

    seen = _record_calls(monkeypatch)

    deploy_cmd._run_deploy(Config())

    assert set(seen) == {step for step, _ in STEPS}


def test_run_deploy_without_a_profile_narrows_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the no-flag path still reaches every step unnarrowed."""
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core.config import Config

    seen = _record_calls(monkeypatch)

    deploy_cmd._run_deploy(Config())

    assert list(seen.values()) == [None] * len(STEPS)


def test_run_deploy_forwards_the_named_profile_to_every_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A step that dropped `only` would deploy every profile from a narrowed run."""
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core.config import Config

    seen = _record_calls(monkeypatch)

    deploy_cmd._run_deploy(Config(), "flex")

    assert list(seen.values()) == ["flex"] * len(STEPS)


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

    monkeypatch.setattr(engine, "agent_for_profile", lambda cfg, name: _Plannerless())

    result = CliRunner().invoke(cli, ["deploy"])

    assert result.exit_code != 0
    assert "plannerless" in result.output
    assert "Traceback" not in result.output
