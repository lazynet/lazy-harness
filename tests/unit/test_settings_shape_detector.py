"""The regression gate: no settings.json the harness writes may contain a
top-level key that Claude Code 2.1.278's own validator treats as a fatal hook
declaration, three levels deep.

`_settings_shape` is a faithful port of the shipped binary's
`gf`/`uW`/`rue`/`r7`/`zs` — this is what actually classifies a settings.json as
safe, not a description of the bug. A detector that can only ever return
"clean" is worthless, so the known-bad cases below are load-bearing: they are
what would catch the next custom top-level key doing to every profile what
`lh_hook_ownership` did.
"""

from __future__ import annotations

import json
from pathlib import Path

from lazy_harness import __version__
from lazy_harness.agents._settings_shape import fatal_hook_shape

GOLDENS = Path(__file__).parent.parent / "goldens" / "config-deploy"


def test_a_recorded_hook_ownership_envelope_is_the_exact_bug_reported() -> None:
    """The bug this repo shipped: `lh_hook_ownership.managed[i].group` is a
    `{"matcher", "hooks"}` object, which is what `r7` matches."""
    document = {
        "hooks": {},
        "lh_hook_ownership": {
            "version": 1,
            "managed": [
                {
                    "event": "SessionStart",
                    "index": 0,
                    "group": {
                        "matcher": "",
                        "hooks": [{"type": "command", "command": "lh hook context-inject"}],
                    },
                }
            ],
        },
    }

    assert fatal_hook_shape(document) == "$.lh_hook_ownership.managed[0].group"


def test_any_top_level_key_can_trip_it_not_just_the_named_one() -> None:
    """The gate must generalise: it is not special-cased on the string
    `lh_hook_ownership`. The next custom key with the same nested shape must
    be caught too, or the gate only prevents this one regression."""
    document = {
        "hooks": {},
        "some_future_harness_ledger": {
            "entries": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "lh x"}]}]
        },
    }

    assert fatal_hook_shape(document) == "$.some_future_harness_ledger.entries[0]"


def test_the_native_hooks_block_itself_is_never_flagged() -> None:
    """Claude Code's own `hooks` block is hook-group shaped by definition —
    scanning under the literal `hooks` key would make every valid settings.json
    fatal, which is not what the shipped detector does."""
    document = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "lh hook x"}]}
            ]
        }
    }

    assert fatal_hook_shape(document) is None


def test_a_known_clean_document_is_not_flagged() -> None:
    document = {"model": "opus", "permissions": {"allow": ["Bash(ls:*)"]}, "hooks": {}}

    assert fatal_hook_shape(document) is None


def test_a_non_object_document_is_not_flagged() -> None:
    """`_as_document` never hands the detector anything but a dict, but the
    detector itself must not crash on the malformed shapes it might still see
    from a caller that skips that normalisation."""
    assert fatal_hook_shape(None) is None
    assert fatal_hook_shape([1, 2, 3]) is None
    assert fatal_hook_shape("not an object") is None


def test_the_pre_fix_golden_would_have_been_discarded_whole() -> None:
    """Demonstrates the gate failing on the shape the harness used to write —
    `git show main:tests/goldens/config-deploy/settings.json` before this
    branch, reproduced inline so the test does not depend on git history."""
    pre_fix_document = json.loads(GOLDENS.joinpath("existing-settings.json").read_text())
    pre_fix_document["lh_hook_ownership"] = {
        "version": 1,
        "managed": [
            {
                "event": "PostToolUse",
                "index": 0,
                "group": pre_fix_document["hooks"]["PostToolUse"][0],
            }
        ],
    }

    assert fatal_hook_shape(pre_fix_document) == "$.lh_hook_ownership.managed[0].group"


def test_every_config_deploy_golden_settings_document_is_clean() -> None:
    for name in ("existing-settings.json", "settings.json"):
        raw = GOLDENS.joinpath(name).read_text().replace("@VERSION@", __version__)
        document = json.loads(raw)

        assert fatal_hook_shape(document) is None, f"{name} would be discarded whole"


def test_a_fresh_profile_deploy_is_clean(tmp_path: Path) -> None:
    from lazy_harness.core.config import Config, HarnessConfig, ProfileEntry, ProfilesConfig
    from lazy_harness.deploy.engine import deploy_hooks

    profile_dir = tmp_path / "profile"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={"personal": ProfileEntry(config_dir=str(profile_dir), roots=["~"])},
        ),
        hooks={},
    )

    deploy_hooks(cfg)

    document = json.loads((profile_dir / "settings.json").read_text())
    assert fatal_hook_shape(document) is None


def test_the_ownership_sidecar_itself_is_never_scanned_as_settings() -> None:
    """The sidecar's whole content is a `{"matcher", "hooks"}` envelope by
    design — the detector is settings.json's gate, not the sidecar's; the
    sidecar living in its own file, outside settings.json entirely, is what
    keeps it out of Claude Code's scan regardless of its own shape."""
    ledger = json.loads(GOLDENS.joinpath("lh-hook-ownership.json").read_text())

    assert ledger["managed"], "fixture should be non-trivial"
    assert fatal_hook_shape(ledger) == "$.managed[0].group"
