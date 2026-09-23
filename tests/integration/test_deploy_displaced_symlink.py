"""A third-party installer that writes `settings.json` atomically, and `lh deploy`.

`deploy_profiles` links `settings.json` into the profile source, so every writer
of that file is really writing the source. An installer that writes atomically —
temp file plus `os.replace`, which is how you avoid leaving a half-written JSON
behind — does not write *through* the link: it replaces the link with a regular
file. The entries then live in the config dir and not in the source.

The next `lh deploy` runs `deploy_profiles` before `deploy_config`, so the link
is restored — and the regular file displaced to `.bak` — before the half of the
deploy that knows how to preserve foreign entries ever reads it. The entries
vanish from the live file without appearing in `preserved` or in `dropped`.

Measured on `lazy-agents` against moshi-hook, the approval bridge of the CT: ten
entries, three reproductions, `grep -c moshi` going 10 -> 0 on both Claude
profiles while the deploy printed a plain success line for `settings.json`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lazy_harness.core.config import Config, ProfileEntry

BRIDGE = "'/usr/local/bin/bridge-hook' agent-hook"

# The shape `bridge-hook install` writes: ten groups over nine events, four of
# them with no matcher at all. Three events — Notification, PermissionRequest
# and Stop — are ones no harness hook is generated for, which is what made the
# event axis look like the cause before the symlink was measured.
BRIDGE_ENTRIES: dict[str, list[dict]] = {
    "Notification": [
        {"matcher": "permission_prompt", "hooks": [{"type": "command", "command": BRIDGE}]}
    ],
    "PermissionRequest": [{"matcher": None, "hooks": [{"type": "command", "command": BRIDGE}]}],
    "PostToolUse": [
        {"matcher": "AskUserQuestion", "hooks": [{"type": "command", "command": BRIDGE}]},
        {"matcher": "ExitPlanMode", "hooks": [{"type": "command", "command": BRIDGE}]},
    ],
    "PreToolUse": [
        {"matcher": "AskUserQuestion", "hooks": [{"type": "command", "command": BRIDGE}]},
        {"matcher": "ExitPlanMode", "hooks": [{"type": "command", "command": BRIDGE}]},
    ],
    "SessionEnd": [{"matcher": None, "hooks": [{"type": "command", "command": BRIDGE}]}],
    "SessionStart": [{"matcher": None, "hooks": [{"type": "command", "command": BRIDGE}]}],
    "Stop": [{"matcher": None, "hooks": [{"type": "command", "command": BRIDGE}]}],
    "UserPromptSubmit": [{"matcher": None, "hooks": [{"type": "command", "command": BRIDGE}]}],
}


def _cfg(home: Path) -> Config:
    cfg = Config()
    cfg.agent.type = "claude-code"
    cfg.profiles.default = "bridge"
    cfg.profiles.items = {
        "bridge": ProfileEntry(config_dir=str(home / "claude-bridge"), agent="claude-code"),
    }
    return cfg


def _seed_source(home: Path) -> Path:
    """The profile source `deploy_profiles` links from."""
    from lazy_harness.core.paths import config_dir

    src = config_dir() / "profiles" / "bridge" / "claude-code"
    src.mkdir(parents=True)
    settings = src / "settings.json"
    settings.write_text("{}\n")
    return settings


def _deploy(cfg: Config) -> None:
    """One `lh deploy`, in the order `_run_deploy` runs the two halves."""
    from lazy_harness.deploy.engine import deploy_config, deploy_profiles

    displaced = deploy_profiles(cfg, only="bridge")
    deploy_config(cfg, only="bridge", displaced=displaced)


def _install_bridge_atomically(target: Path) -> None:
    """What a temp-file-plus-rename installer does to a symlinked target.

    It reads the current document (through the link), adds its own entries, and
    renames its temp file over the target. The rename is the whole point — it is
    also what turns the link into a regular file.
    """
    document = json.loads(target.read_text())
    hooks = document.setdefault("hooks", {})
    for event, groups in BRIDGE_ENTRIES.items():
        hooks.setdefault(event, []).extend(json.loads(json.dumps(groups)))
    scratch = target.with_name(target.name + ".installer-tmp")
    scratch.write_text(json.dumps(document, indent=2) + "\n")
    os.replace(scratch, target)


def _bridge_commands(document: object) -> list[str]:
    assert isinstance(document, dict)
    hooks = document.get("hooks", {})
    assert isinstance(hooks, dict)
    return [
        handler["command"]
        for groups in hooks.values()
        for group in groups
        for handler in group.get("hooks", [])
        if handler.get("command") == BRIDGE
    ]


@pytest.fixture
def deployed(home_dir: Path) -> tuple[Config, Path, Path]:
    """A profile through one full deploy, with the bridge then installed over it."""
    cfg = _cfg(home_dir)
    source = _seed_source(home_dir)
    _deploy(cfg)

    live = home_dir / "claude-bridge" / "settings.json"
    assert live.is_symlink(), "the first deploy is what puts the link there"

    _install_bridge_atomically(live)
    assert not live.is_symlink(), "an atomic rename replaces the link, not its target"
    assert len(_bridge_commands(json.loads(live.read_text()))) == 10

    return cfg, live, source


def test_a_displaced_installers_entries_survive_the_next_deploy(
    deployed: tuple[Config, Path, Path],
) -> None:
    """The entries the harness never generated are still there afterwards.

    This is the whole point: the bridge is an approval gate, so a deploy that
    leaves it uninvoked is a security control that turned itself off. Failing
    here means `lh deploy` silently uninstalled another tool's hooks.
    """
    cfg, live, _ = deployed

    _deploy(cfg)

    assert len(_bridge_commands(json.loads(live.read_text()))) == 10


def test_the_surviving_entries_land_in_the_profile_source(
    deployed: tuple[Config, Path, Path],
) -> None:
    """Not just in the config dir — in the file the link points at.

    Surviving only in the config dir would mean the link was left broken, and
    the entries would be displaced again by the deploy after this one.
    """
    cfg, live, source = deployed

    _deploy(cfg)

    assert live.is_symlink(), "the link is restored, so the source is the real file"
    assert len(_bridge_commands(json.loads(source.read_text()))) == 10


def test_the_displacement_is_reported_rather_than_silent(
    deployed: tuple[Config, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """A regular file where a link belongs is news, and a checkmark is not news.

    The entry that vanished appeared in neither `preserved` nor `dropped`, which
    is worth a diagnostic on its own even in the runs where the displacement is
    harmless.
    """
    cfg, _, _ = deployed

    _deploy(cfg)

    out = capsys.readouterr().out
    assert "settings.json" in out
    assert "displaced" in out, out
    assert "settings.json.bak" in out, out


def test_deploy_profiles_displacement_report_explains_atomic_replacement(
    deployed: tuple[Config, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.deploy.engine import deploy_profiles

    cfg, _, _ = deployed
    capsys.readouterr()

    deploy_profiles(cfg, only="bridge")

    out = capsys.readouterr().out
    assert (
        "a writer that replaces this path (temp file plus rename) breaks it "
        "instead of writing through it."
    ) in out


def test_the_entries_are_named_as_preserved_by_the_config_half(
    deployed: tuple[Config, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The displaced document reaches the merge, so its foreign entries report."""
    cfg, _, _ = deployed

    _deploy(cfg)

    out = capsys.readouterr().out
    assert "preserved 10" in out, out
    assert BRIDGE in out, out
