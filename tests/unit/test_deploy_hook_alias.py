"""`lh deploy` nudges a profile off a renamed hook's old key.

`post-tool-use-sync-claude` became `post-tool-use-sync-system-doc` (decision 5,
2026-09-13 multi-agent blast-radius design). The old key must keep deploying
the same module — a shared `config.toml` synced across machines cannot be
renamed atomically — but the operator needs a nudge to make the move, not
silence about which key is now doing the work.
"""

from __future__ import annotations

import pytest

from lazy_harness.core.config import Config, HookEventConfig, ProfileEntry


def _cfg(hook_name: str) -> Config:
    cfg = Config()
    cfg.agent.type = "claude-code"
    cfg.profiles.default = "p1"
    cfg.profiles.items = {"p1": ProfileEntry(config_dir="~/.agent-p1", agent="claude-code")}
    cfg.hooks = {"post_tool_use": HookEventConfig(scripts=[hook_name])}
    return cfg


def test_the_old_key_still_deploys_the_new_module() -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    entries = _hook_entries_for(_cfg("post-tool-use-sync-claude"), "p1", "lh")

    assert [e.command for e in entries["post_tool_use"]] == [
        "lh hook post-tool-use-sync-claude --profile p1"
    ]


def test_the_old_key_prints_a_rename_notice(capsys: pytest.CaptureFixture[str]) -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    _hook_entries_for(_cfg("post-tool-use-sync-claude"), "p1", "lh")

    assert (
        "hook 'post-tool-use-sync-claude' is now 'post-tool-use-sync-system-doc'; "
        "rename it in config.toml" in capsys.readouterr().out
    )


def test_the_new_key_prints_nothing() -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    entries = _hook_entries_for(_cfg("post-tool-use-sync-system-doc"), "p1", "lh")

    assert [e.command for e in entries["post_tool_use"]] == [
        "lh hook post-tool-use-sync-system-doc --profile p1"
    ]


def test_the_new_key_deploy_is_silent(capsys: pytest.CaptureFixture[str]) -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    _hook_entries_for(_cfg("post-tool-use-sync-system-doc"), "p1", "lh")

    assert capsys.readouterr().out == ""


def test_a_misspelled_key_gets_no_rename_notice(capsys: pytest.CaptureFixture[str]) -> None:
    """Not a new diagnostic path: an unresolvable name is silently dropped by
    `resolve_script_names`, same as before this hook existed."""
    from lazy_harness.deploy.engine import _hook_entries_for

    entries = _hook_entries_for(_cfg("post-tool-use-sync-clod"), "p1", "lh")

    assert "post_tool_use" not in entries
    assert capsys.readouterr().out == ""
