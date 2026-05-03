"""Tests for the lh deploy CLI command."""

from __future__ import annotations

import pytest


def test_run_deploy_invokes_deploy_mcp_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.core.config import Config

    called: dict[str, bool] = {
        "profiles": False,
        "hooks": False,
        "mcp": False,
        "symlink": False,
    }

    monkeypatch.setattr(
        deploy_cmd, "deploy_profiles", lambda cfg: called.__setitem__("profiles", True)
    )
    monkeypatch.setattr(deploy_cmd, "deploy_hooks", lambda cfg: called.__setitem__("hooks", True))
    monkeypatch.setattr(
        deploy_cmd, "deploy_mcp_servers", lambda cfg: called.__setitem__("mcp", True)
    )
    monkeypatch.setattr(
        deploy_cmd, "deploy_claude_symlink", lambda cfg: called.__setitem__("symlink", True)
    )

    deploy_cmd._run_deploy(Config())

    assert called["mcp"] is True
    assert called["profiles"] is True
    assert called["hooks"] is True
    assert called["symlink"] is True
