"""`lh profile sync-claude-md` became `lh profile sync-system-doc` (decision 5).

The old name stays registered — a hidden alias to the same command, not a
second implementation — so a script or muscle memory typing the old name
keeps working. `lh profile --help` should not advertise it as a live option
going forward, which is what `hidden=True` is for.
"""

from __future__ import annotations

from lazy_harness.cli.profile_cmd import profile


def test_sync_system_doc_is_registered_and_visible() -> None:
    cmd = profile.commands.get("sync-system-doc")
    assert cmd is not None
    assert cmd.hidden is False


def test_sync_claude_md_is_registered_and_hidden() -> None:
    cmd = profile.commands.get("sync-claude-md")
    assert cmd is not None
    assert cmd.hidden is True


def test_both_names_invoke_the_same_callback() -> None:
    """One implementation, two names -- not a fork that can drift apart."""
    new_cmd = profile.commands["sync-system-doc"]
    old_cmd = profile.commands["sync-claude-md"]
    assert old_cmd.callback is new_cmd.callback


def test_sync_claude_md_does_not_appear_in_the_visible_help_listing() -> None:
    from click.testing import CliRunner

    result = CliRunner().invoke(profile, ["--help"])

    assert "sync-system-doc" in result.output
    assert "sync-claude-md" not in result.output
