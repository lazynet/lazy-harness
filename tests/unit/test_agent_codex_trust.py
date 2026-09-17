"""Codex hook trust, as far as `lh doctor` may claim it.

The key formula and the three-way status below are the design's, measured on
`codex-cli 0.154.0`: the decisive probe found a byte-identical handler reading
`Trusted` from `hooks.json` while the `config.toml` declaration of the same
thing read `new · review required`, with the *same* `trusted_hash`. So the hash
is stable across representations and the key is not.

Nothing here asserts a hook is trusted. That is the point: establishing it needs
`current_hash`, which the harness deliberately does not compute.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from lazy_harness.agents.base import HookEntry
from lazy_harness.agents.codex import _HOOK_EVENTS, CodexAdapter, trust_keys
from lazy_harness.agents.codex_trust import collect_codex_trust, trust_for_profile
from lazy_harness.core.config import Config, ProfileEntry

_HASH = "sha256:904128e4c0ffee0000000000000000000000000000000000000000000000dead"


def _hooks_document(events: dict[str, list[HookEntry]]) -> str:
    ops = CodexAdapter().plan_config(events, {}, {})
    assert ops and ops[0].artifact is not None
    return ops[0].artifact.content


def _profile(tmp_path: Path, *, agent: str = "codex") -> Config:
    cfg = Config()
    cfg.profiles.items = {"probe": ProfileEntry(config_dir=str(tmp_path), agent=agent)}
    cfg.profiles.default = "probe"
    return cfg


def _deploy(tmp_path: Path, events: dict[str, list[HookEntry]] | None = None) -> Path:
    declared = events or {
        "session_start": [HookEntry(command="lh hook context-inject --profile probe")],
        "pre_tool_use": [HookEntry(command="lh hook pre-tool-use-security --profile probe")],
    }
    path = tmp_path / "hooks.json"
    path.write_text(_hooks_document(declared))
    return path


def _config_toml(tmp_path: Path, state: dict[str, str]) -> Path:
    body = "".join(f'[hooks.state."{key}"]\ntrusted_hash = "{_HASH}"\n\n' for key in state)
    path = tmp_path / "config.toml"
    path.write_text(body)
    return path


# --- the key formula ------------------------------------------------------


def test_the_key_is_the_file_path_the_snake_case_event_and_two_indices(tmp_path: Path) -> None:
    """Measured on 0.154.0. Two details the same probe settled and this pins:
    the key uses the **snake_case** event name even though the declaration must
    be PascalCase, and both indices are positions in the file."""
    hooks_file = _deploy(tmp_path, {"session_start": [HookEntry(command="a")]})
    declared, ignored = trust_keys(hooks_file, hooks_file.read_text())

    assert [key for key, _ in declared] == [f"{hooks_file}:session_start:0:0"]
    assert ignored == ()


def test_each_group_gets_its_own_index_in_declaration_order(tmp_path: Path) -> None:
    hooks_file = _deploy(
        tmp_path,
        {"pre_tool_use": [HookEntry(command="first"), HookEntry(command="second")]},
    )
    declared, _ = trust_keys(hooks_file, hooks_file.read_text())

    assert [key for key, _ in declared] == [
        f"{hooks_file}:pre_tool_use:0:0",
        f"{hooks_file}:pre_tool_use:1:0",
    ]


def test_every_event_keys_on_the_name_codex_writes_not_the_canonical_one(
    tmp_path: Path,
) -> None:
    """The event segment is snake_case of Codex's **own** name for the event,
    not of the harness's canonical one. Measured 2026-09-17 on `codex-cli
    0.154.0`: a profile whose `hooks.json` declares `Stop` carries
    `[hooks.state."<path>:stop:0:0"]`, while the harness generated
    `session_stop` and reported six approved hooks as untrusted plus six
    orphaned entries.

    The loop is the assertion. `session_stop` is today the only canonical name
    that is not already snake_case of its native one, so a test naming it would
    go green again the day a second divergence lands.
    """
    for canonical, support in _HOOK_EVENTS.items():
        hooks_file = _deploy(tmp_path, {canonical: [HookEntry(command="a")]})
        declared, ignored = trust_keys(hooks_file, hooks_file.read_text())

        native_snake = re.sub(r"(?<!^)(?=[A-Z])", "_", support.native_name).lower()
        assert ignored == ()
        assert [key for key, _ in declared] == [f"{hooks_file}:{native_snake}:0:0"], (
            f"{canonical} keys on its canonical name; codex writes {native_snake!r}"
        )


def test_the_path_is_absolute_because_the_key_is(tmp_path: Path) -> None:
    """A relative declaring path would key every hook under a different string
    than the one Codex wrote, and every hook would read untrusted forever."""
    hooks_file = _deploy(tmp_path, {"session_start": [HookEntry(command="a")]})
    declared, _ = trust_keys(Path("hooks.json"), hooks_file.read_text())

    assert declared[0][0].startswith(f"{Path('hooks.json').resolve()}:")


def test_an_event_name_codex_does_not_deliver_is_named_rather_than_dropped(
    tmp_path: Path,
) -> None:
    """A hand-edited `hooks.json` can carry anything. Silently skipping an event
    would report "all trusted" over a declaration nobody looked at."""
    hooks_file = tmp_path / "hooks.json"
    hooks_file.write_text(
        json.dumps({"hooks": {"Nonsense": [{"hooks": [{"type": "command", "command": "x"}]}]}})
    )
    declared, ignored = trust_keys(hooks_file, hooks_file.read_text())

    assert declared == ()
    assert ignored == ("Nonsense",)


@pytest.mark.parametrize(
    "raw",
    ["not json", "[]", '"a string"', "7", "null", '{"hooks": 7}', '{"hooks": {"PreToolUse": 7}}'],
)
def test_a_document_that_is_not_the_expected_shape_declares_nothing(
    tmp_path: Path, raw: str
) -> None:
    """Valid JSON of the wrong type alongside malformed JSON — a hook trust
    report must not raise on either."""
    declared, ignored = trust_keys(tmp_path / "hooks.json", raw)

    assert declared == ()
    assert ignored == ()


# --- the three states doctor may report -----------------------------------


def test_no_stored_hash_reads_untrusted(tmp_path: Path) -> None:
    _deploy(tmp_path)
    _config_toml(tmp_path, {})

    report = trust_for_profile(_profile(tmp_path), "probe")

    assert report is not None
    assert report.declared == 2
    assert len(report.untrusted) == 2
    assert report.unknown == ()
    assert report.orphaned == ()


def test_a_stored_hash_reads_unknown_and_never_trusted(tmp_path: Path) -> None:
    """The whole restraint of this module in one assertion: a hash was stored,
    and whether it still matches is not determinable without Codex's own
    normalisation. `unknown` is not a weaker word for `trusted`."""
    hooks_file = _deploy(tmp_path)
    declared, _ = trust_keys(hooks_file, hooks_file.read_text())
    _config_toml(tmp_path, {key: _HASH for key, _ in declared})

    report = trust_for_profile(_profile(tmp_path), "probe")

    assert report is not None
    assert report.untrusted == ()
    assert len(report.unknown) == 2
    assert not hasattr(report, "trusted")


def test_a_stop_hook_codex_approved_is_neither_untrusted_nor_orphaned(tmp_path: Path) -> None:
    """The doctor-level shape of the same defect: one `Stop` handler, one
    `[hooks.state]` entry spelled the way Codex spells it. Keying on the
    canonical name made this one report say "untrusted" *and* "orphaned" about
    the same approved handler — the two halves of one mismatch, counted twice.
    """
    hooks_file = _deploy(tmp_path, {"session_stop": [HookEntry(command="a")]})
    _config_toml(tmp_path, {f"{hooks_file.resolve()}:stop:0:0": _HASH})

    report = trust_for_profile(_profile(tmp_path), "probe")

    assert report is not None
    assert report.untrusted == ()
    assert report.unknown == ("session_stop[0]",)
    assert report.orphaned == ()


def test_a_changed_declaration_since_the_last_snapshot_reads_stale(home_dir: Path) -> None:
    """The fourth state, established without recomputing anything Codex does:
    the harness's own deploy snapshot proves this hook's declaration is not
    what it was the last time a hash could have been approved."""
    from lazy_harness.core.backups import DEPLOY_NAMESPACE, backups_root, namespace_dir
    from lazy_harness.deploy.snapshot import take_snapshot

    profile_dir = home_dir / ".codex"
    profile_dir.mkdir()
    old_hooks = {"pre_tool_use": [HookEntry(command="lh hook sec", matcher="Bash")]}
    hooks_file = _deploy(profile_dir, old_hooks)
    declared, _ = trust_keys(hooks_file, hooks_file.read_text())
    _config_toml(profile_dir, {key: _HASH for key, _ in declared})

    snapshot_dir = namespace_dir(backups_root(), DEPLOY_NAMESPACE) / "20260101-000000.000000"
    take_snapshot([hooks_file], snapshot_dir)

    new_hooks = {"pre_tool_use": [HookEntry(command="lh hook sec", matcher="Edit")]}
    _deploy(profile_dir, new_hooks)

    report = trust_for_profile(_profile(profile_dir), "probe")

    assert report is not None
    assert report.stale == ("pre_tool_use[0]",)
    assert report.unknown == ()


def test_an_unchanged_redeploy_after_a_snapshot_still_reads_unknown(home_dir: Path) -> None:
    """A snapshot existing is not itself a reason to call anything stale — only
    a declaration that actually differs from it is."""
    from lazy_harness.core.backups import DEPLOY_NAMESPACE, backups_root, namespace_dir
    from lazy_harness.deploy.snapshot import take_snapshot

    profile_dir = home_dir / ".codex"
    profile_dir.mkdir()
    hooks = {"pre_tool_use": [HookEntry(command="lh hook sec", matcher="Bash")]}
    hooks_file = _deploy(profile_dir, hooks)
    declared, _ = trust_keys(hooks_file, hooks_file.read_text())
    _config_toml(profile_dir, {key: _HASH for key, _ in declared})

    snapshot_dir = namespace_dir(backups_root(), DEPLOY_NAMESPACE) / "20260101-000000.000000"
    take_snapshot([hooks_file], snapshot_dir)

    _deploy(profile_dir, hooks)  # redeploy of the identical declaration

    report = trust_for_profile(_profile(profile_dir), "probe")

    assert report is not None
    assert report.stale == ()
    assert len(report.unknown) == 1


def test_a_state_entry_the_file_no_longer_declares_is_orphaned(tmp_path: Path) -> None:
    """The one state the harness can establish on its own. The key indexes the
    group's *position*, so a redeploy that drops a group leaves the approval
    behind pointing at a handler that is gone."""
    hooks_file = _deploy(tmp_path)
    declared, _ = trust_keys(hooks_file, hooks_file.read_text())
    stale = f"{hooks_file}:pre_tool_use:7:0"
    _config_toml(tmp_path, {**{key: _HASH for key, _ in declared}, stale: _HASH})

    report = trust_for_profile(_profile(tmp_path), "probe")

    assert report is not None
    assert report.orphaned == (stale,)


def test_a_state_entry_for_another_file_is_not_this_profiles_orphan(tmp_path: Path) -> None:
    """Codex keys trust per declaring file and loads several layers. An entry
    for someone else's `hooks.json` is their business, not a stale approval."""
    hooks_file = _deploy(tmp_path)
    declared, _ = trust_keys(hooks_file, hooks_file.read_text())
    foreign = "/somewhere/else/hooks.json:pre_tool_use:0:0"
    _config_toml(tmp_path, {**{key: _HASH for key, _ in declared}, foreign: _HASH})

    report = trust_for_profile(_profile(tmp_path), "probe")

    assert report is not None
    assert report.orphaned == ()


# --- what cannot be established is said, not guessed ----------------------


def test_an_absent_config_toml_reads_as_every_hook_untrusted(tmp_path: Path) -> None:
    """Codex writes this file on its first run, so its absence means the profile
    has never been used — which is untrusted, not unreadable."""
    _deploy(tmp_path)

    report = trust_for_profile(_profile(tmp_path), "probe")

    assert report is not None
    assert report.unreadable == ""
    assert len(report.untrusted) == 2


def test_a_config_toml_that_does_not_parse_reports_that_and_claims_nothing(
    tmp_path: Path,
) -> None:
    """Reporting "0 untrusted" over a file that could not be read is the worst
    of the three outcomes, because it looks like the good one."""
    _deploy(tmp_path)
    (tmp_path / "config.toml").write_text("[hooks.state\nbroken")

    report = trust_for_profile(_profile(tmp_path), "probe")

    assert report is not None
    assert "config.toml" in report.unreadable
    assert report.untrusted == ()
    assert report.unknown == ()


def test_a_hooks_state_that_is_not_a_table_is_ignored_rather_than_indexed(
    tmp_path: Path,
) -> None:
    _deploy(tmp_path)
    (tmp_path / "config.toml").write_text('hooks = "not a table"\n')

    report = trust_for_profile(_profile(tmp_path), "probe")

    assert report is not None
    assert report.unreadable == ""
    assert len(report.untrusted) == 2


# --- scope ----------------------------------------------------------------


def test_a_profile_that_does_not_run_codex_reports_nothing(tmp_path: Path) -> None:
    _deploy(tmp_path)

    assert trust_for_profile(_profile(tmp_path, agent="claude-code"), "probe") is None


def test_a_codex_profile_with_no_deployed_hooks_reports_nothing(tmp_path: Path) -> None:
    """A line on every `lh doctor` saying a profile has no hooks trains the
    reader past the line that matters."""
    assert trust_for_profile(_profile(tmp_path), "probe") is None


def test_the_collector_walks_every_profile(tmp_path: Path) -> None:
    codex_dir, claude_dir = tmp_path / "codex", tmp_path / "claude"
    codex_dir.mkdir()
    claude_dir.mkdir()
    _deploy(codex_dir)
    _deploy(claude_dir)

    cfg = Config()
    cfg.profiles.items = {
        "cx": ProfileEntry(config_dir=str(codex_dir), agent="codex"),
        "cc": ProfileEntry(config_dir=str(claude_dir), agent="claude-code"),
    }
    cfg.profiles.default = "cc"

    assert [r.profile for r in collect_codex_trust(cfg)] == ["cx"]
