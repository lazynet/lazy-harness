"""Unit tests for post_tool_use_sync_claude hook."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _payload(tool: str, path: str) -> str:
    return json.dumps({"tool_name": tool, "tool_input": {"file_path": path}})


@pytest.fixture(autouse=True)
def _no_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point config resolution at an empty dir — a machine with no config.toml.

    Without this the hook reads whatever config the developer happens to have,
    so the suite only ever exercised the configured path.
    """
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path / "config"))


def test_triggers_on_head_edit_under_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_claude as mod

    fake_sync = MagicMock(return_value=[])
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(_payload("Edit", "/x/.config/lazy-harness/profiles/lazy/CLAUDE.head.md")),
    )

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    fake_sync.assert_called_once()
    args = fake_sync.call_args[0]
    assert args[0] == Path("/x/.config/lazy-harness/profiles")
    # No config.toml → fall back to the default adapter rather than skipping.
    assert args[1].name == "claude-code"


def test_triggers_on_tail_write_under_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_claude as mod

    fake_sync = MagicMock(return_value=[])
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(_payload("Write", "/x/.config/lazy-harness/profiles/flex/CLAUDE.tail.md")),
    )

    with pytest.raises(SystemExit):
        mod.main()
    fake_sync.assert_called_once()


def test_triggers_on_common_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_claude as mod

    fake_sync = MagicMock(return_value=[])
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(_payload("Edit", "/x/.config/lazy-harness/profiles/_common/CLAUDE.common.md")),
    )
    with pytest.raises(SystemExit):
        mod.main()
    fake_sync.assert_called_once()


def test_skips_unrelated_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_claude as mod

    fake_sync = MagicMock()
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(_payload("Edit", "/x/.config/lazy-harness/profiles/lazy/settings.json")),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    fake_sync.assert_not_called()


def test_skips_non_edit_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_claude as mod

    fake_sync = MagicMock()
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(_payload("Read", "/x/.config/lazy-harness/profiles/lazy/CLAUDE.head.md")),
    )
    with pytest.raises(SystemExit):
        mod.main()
    fake_sync.assert_not_called()


def test_skips_segment_outside_profiles_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `CLAUDE.head.md` outside a `profiles/<name>/` tree must not trigger."""
    from lazy_harness.hooks.builtins import post_tool_use_sync_claude as mod

    fake_sync = MagicMock()
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(_payload("Edit", "/some/other/repo/CLAUDE.head.md")),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    fake_sync.assert_not_called()


def test_swallows_sync_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """If sync_profiles raises, the hook still exits 0 — never block the agent."""
    from lazy_harness.hooks.builtins import post_tool_use_sync_claude as mod

    def boom(*_: object, **__: object) -> object:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(mod, "sync_profiles", boom)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(_payload("Edit", "/x/.config/lazy-harness/profiles/lazy/CLAUDE.head.md")),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0


def test_swallows_malformed_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_claude as mod

    fake_sync = MagicMock()
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    fake_sync.assert_not_called()
