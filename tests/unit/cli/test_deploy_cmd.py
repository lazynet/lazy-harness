"""Tests for the lh deploy CLI command."""

from __future__ import annotations

import pytest


def _record_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Replace each deploy step with a recorder of the `only` it received."""
    from lazy_harness.cli import deploy_cmd

    seen: dict[str, object] = {}

    def recorder(step: str):
        def _call(cfg, *, only=None) -> None:
            seen[step] = only

        return _call

    for step, attr in (
        ("profiles", "deploy_profiles"),
        ("hooks", "deploy_hooks"),
        ("mcp", "deploy_mcp_servers"),
        ("symlink", "deploy_claude_symlink"),
    ):
        monkeypatch.setattr(deploy_cmd, attr, recorder(step))
    return seen


def test_run_deploy_invokes_every_step(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core.config import Config

    seen = _record_calls(monkeypatch)

    deploy_cmd._run_deploy(Config())

    assert set(seen) == {"profiles", "hooks", "mcp", "symlink"}


def test_run_deploy_without_a_profile_narrows_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the no-flag path still reaches every step unnarrowed."""
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core.config import Config

    seen = _record_calls(monkeypatch)

    deploy_cmd._run_deploy(Config())

    assert list(seen.values()) == [None, None, None, None]


def test_run_deploy_forwards_the_named_profile_to_every_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A step that dropped `only` would deploy every profile from a narrowed run."""
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core.config import Config

    seen = _record_calls(monkeypatch)

    deploy_cmd._run_deploy(Config(), "flex")

    assert list(seen.values()) == ["flex", "flex", "flex", "flex"]
