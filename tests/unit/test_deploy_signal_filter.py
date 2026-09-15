"""Deploy skips a hook whose declared signals its profile's agent cannot deliver.

`BuiltinHookSpec.signals` was introduced to stop `stop-verify-guard` installing
on an agent that supplies no goal marker, where it would run, find nothing and
pass — a hook that cannot fail, reported green. Until this filter existed the
declaration was inert: `collect_hook_signal_gaps` named the gap in `lh doctor`
*after* the deploy had already written the hook.

The omission lines are asserted as literal text, not as an absence in the
artifact. A hook that disappears from a deploy without being named is the same
silent failure wearing the other mask.
"""

from __future__ import annotations

import pytest

from lazy_harness.core.config import Config, HookEventConfig, ProfileEntry


def _cfg(agent: str) -> Config:
    """One profile running `agent`, wired to the one hook that declares a signal."""
    cfg = Config()
    cfg.agent.type = agent
    cfg.profiles.default = "p1"
    cfg.profiles.items = {"p1": ProfileEntry(config_dir="~/.agent-p1", agent=agent)}
    cfg.hooks = {"session_stop": HookEventConfig(scripts=["stop-verify-guard"])}
    return cfg


def _hook_names(entries: dict) -> set[str]:
    """The builtin names behind a profile's generated commands.

    Reads them back out of `lh hook <name> --profile <profile>` rather than
    trusting the input list, so the assertion is about what deploy would write.
    """
    names = set()
    for event_entries in entries.values():
        for entry in event_entries:
            parts = entry.command.split()
            if "hook" in parts:
                names.add(parts[parts.index("hook") + 1])
    return names


def test_hook_whose_signal_the_agent_cannot_deliver_is_not_deployed() -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    entries = _hook_entries_for(_cfg("codex"), "p1", "lh")

    assert "session_stop" not in entries


def test_the_same_hook_is_deployed_to_an_agent_that_delivers_the_signal() -> None:
    """The filter narrows on the signal, not on the hook's name."""
    from lazy_harness.deploy.engine import _hook_entries_for

    entries = _hook_entries_for(_cfg("claude-code"), "p1", "lh")

    assert [e.command for e in entries["session_stop"]] == [
        "lh hook stop-verify-guard --profile p1"
    ]


def test_the_omitted_hook_is_named_with_its_profile_and_missing_signal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    _hook_entries_for(_cfg("codex"), "p1", "lh")

    assert (
        "stop-verify-guard omitted in 'p1': agent 'codex' does not deliver goal_status"
        in capsys.readouterr().out
    )


def test_nothing_is_reported_when_every_signal_is_deliverable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    _hook_entries_for(_cfg("claude-code"), "p1", "lh")

    assert "omitted" not in capsys.readouterr().out


def test_deploy_omits_exactly_the_pairs_doctor_reports() -> None:
    """The gate's one-importable-place rule, asserted by running both readers.

    Deploy and `lh doctor` answer the same derived question. If they resolved it
    separately the first change to either would put a hook in the artifact that
    doctor swore was absent, or the reverse.
    """
    from lazy_harness.deploy.engine import _hook_entries_for
    from lazy_harness.hooks.signal_gaps import collect_hook_signal_gaps

    cfg = _cfg("codex")
    gaps = collect_hook_signal_gaps(cfg)
    assert gaps, "fixture must produce at least one gap for this to mean anything"

    deployed = _hook_names(_hook_entries_for(cfg, "p1", "lh"))

    assert deployed.isdisjoint({g.hook for g in gaps})


def test_a_hook_doctor_does_not_report_is_still_deployed() -> None:
    """The other direction: the filter removes the reported pairs and no more."""
    from lazy_harness.deploy.engine import _hook_entries_for
    from lazy_harness.hooks.signal_gaps import collect_hook_signal_gaps

    cfg = _cfg("codex")
    cfg.hooks["pre_tool_use"] = HookEventConfig(
        scripts=["stop-verify-guard", "pre-tool-use-security"]
    )

    reported = {g.hook for g in collect_hook_signal_gaps(cfg)}
    deployed = _hook_names(_hook_entries_for(cfg, "p1", "lh"))

    assert "pre-tool-use-security" not in reported
    assert "pre-tool-use-security" in deployed


# --- per-placement signals, which is the whole reason the field widened ------ #


def _gauge_cfg(agent: str) -> Config:
    """One profile wired to `herdr-context-gauge` exactly as a real one is.

    Four placements, matching the live deployment: `SessionStart`, `Stop`,
    `SessionEnd` and `PostToolUse`. This hook ships in no default list — it
    attaches wherever the operator puts it (`plugins/builtins.py:60-64`) — so
    the config has to name it on each.
    """
    cfg = Config()
    cfg.agent.type = agent
    cfg.profiles.default = "p1"
    cfg.profiles.items = {"p1": ProfileEntry(config_dir="~/.agent-p1", agent=agent)}
    cfg.hooks = {
        event: HookEventConfig(scripts=["herdr-context-gauge"])
        for event in ("session_start", "session_stop", "session_end", "post_tool_use")
    }
    return cfg


def test_the_retract_survives_on_an_agent_that_cannot_deliver_token_usage() -> None:
    """The failure the per-placement declaration exists to prevent.

    A flat `TOKEN_USAGE` on this spec would omit all four placements on a
    reader-less agent, and the one that would hurt is `session_end`: panes
    outlive sessions and pane metadata is persistent, so with nothing left to
    clear the gauge, a dead session's window stays on display indefinitely.
    The retract reads no transcript (`herdr_context_gauge.py:175`), so it has
    no signal to be missing and must install.
    """
    from lazy_harness.deploy.engine import _hook_entries_for

    entries = _hook_entries_for(_gauge_cfg("codex"), "p1", "lh")

    assert "session_end" in entries
    assert [e.command for e in entries["session_end"]] == [
        "lh hook herdr-context-gauge --profile p1"
    ]


@pytest.mark.parametrize("event", ["session_start", "session_stop", "post_tool_use"])
def test_the_publishing_placements_are_omitted_on_that_same_agent(event: str) -> None:
    """The other half: the three that *do* read the window are left out.

    Without this the test above passes just as well against a spec declaring
    nothing at all, which would install three placements that can never produce
    a reading — green because they cannot fail.
    """
    from lazy_harness.deploy.engine import _hook_entries_for

    entries = _hook_entries_for(_gauge_cfg("codex"), "p1", "lh")

    assert event not in entries


def test_every_placement_is_deployed_to_an_agent_that_delivers_the_signal() -> None:
    """Claude Code supplies token usage, so nothing is filtered there.

    Asserted on the gauge's own presence per event rather than on the key set:
    `merge_with_defaults` also folds in the hooks every profile gets by default,
    which are not what this test is about.
    """
    from lazy_harness.deploy.engine import _hook_entries_for

    entries = _hook_entries_for(_gauge_cfg("claude-code"), "p1", "lh")

    placed = {
        event
        for event, event_entries in entries.items()
        if any("herdr-context-gauge" in e.command for e in event_entries)
    }
    assert placed == {"session_start", "session_stop", "session_end", "post_tool_use"}


def test_each_omitted_placement_is_named_on_its_own_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Printed per event, because a hook omitted from three is three absences.

    Collapsing them would leave the operator reading one line and assuming the
    other two placements installed.
    """
    from lazy_harness.deploy.engine import _hook_entries_for

    _hook_entries_for(_gauge_cfg("codex"), "p1", "lh")

    omissions = [
        line
        for line in capsys.readouterr().out.splitlines()
        if "herdr-context-gauge omitted" in line
    ]
    assert len(omissions) == 3
    assert all("does not deliver token_usage" in line for line in omissions)
