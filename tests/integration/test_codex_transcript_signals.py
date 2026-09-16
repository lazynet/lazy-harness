"""What a Codex profile's hooks can be fed, once the reader exists.

The reader is wired by nothing: `_shared.transcript_reader` resolves it with
`isinstance(adapter, TranscriptReader)`, so adding the three methods to
`CodexAdapter` flips every caller at once. These tests hold both halves of that
flip against decision 11 of
`specs/designs/2026-09-13-multi-agent-harness-design.md`:

* the three signals Codex's rollout carries stop being gaps — the hooks that
  need them are fed and deploy installs them; and
* `GOAL_STATUS` stays a gap, and the diagnostic changes from *no reader* to *a
  reader that does not deliver it*, because those are different repairs.

Invoked through `lh doctor` rather than through the collector, for the reason
`test_deploy_signal_agreement.py` gives: reading the shared helper proves only
that one function returns what it returns.
"""

from __future__ import annotations

import re
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    HookEventConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)
from lazy_harness.core.paths import config_dir


def _write_config(home_dir: Path, hooks: dict[str, HookEventConfig] | None = None) -> Path:
    codex_home = home_dir / ".codex-p1"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="p1",
            items={"p1": ProfileEntry(config_dir=str(codex_home), agent="codex")},
        ),
    )
    cfg.agent.type = "codex"
    if hooks is not None:
        cfg.hooks = hooks
    save_config(cfg, config_dir() / "config.toml")
    return codex_home


def _flat_hook_signals(output: str) -> str:
    """The Hook signals section, unwrapped — rich breaks lines at the width."""
    return re.sub(r"\s+", " ", output.partition("Hook signals")[2])


# --- the reader resolves for a Codex profile --------------------------------


def test_transcript_reader_resolves_the_codex_adapter(home_dir: Path) -> None:
    from lazy_harness.agents.codex import CodexAdapter
    from lazy_harness.hooks.builtins._shared import transcript_reader

    _write_config(home_dir)

    assert isinstance(transcript_reader("p1"), CodexAdapter)


def test_the_resolved_reader_declares_codex_signals(home_dir: Path) -> None:
    from lazy_harness.agents.base import Signal
    from lazy_harness.hooks.builtins._shared import transcript_reader

    _write_config(home_dir)
    reader = transcript_reader("p1")

    assert reader is not None
    assert reader.signals() == {Signal.MESSAGES, Signal.TOOL_CALLS, Signal.TOKEN_USAGE}


# --- the gaps the reader closes ---------------------------------------------


def test_the_default_hook_set_has_no_signal_gap_on_codex(home_dir: Path) -> None:
    """`session-export` (messages) and `stop-context-rotate` (token_usage) were
    the two the default set could not feed before this reader existed."""
    from lazy_harness.core.config import load_config
    from lazy_harness.core.paths import config_file
    from lazy_harness.hooks.signal_gaps import gaps_for_profile

    _write_config(home_dir)
    cfg = load_config(config_file())

    assert gaps_for_profile(cfg, "p1") == []


def test_a_codex_profile_deploys_the_hooks_that_read_messages_and_tokens(
    home_dir: Path,
) -> None:
    """The deploy side of the same answer — the gate is `hooks.json`, not a set."""
    from lazy_harness.cli.main import cli

    codex_home = _write_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy", "--profile", "p1"])

    assert result.exit_code == 0, result.output
    written = (codex_home / "hooks.json").read_text()
    assert "session-export" in written
    assert "stop-context-rotate" in written


# --- the gap the reader must not close --------------------------------------


def test_goal_status_is_still_missing_and_named_as_a_reader_gap(home_dir: Path) -> None:
    from lazy_harness.agents.base import Signal
    from lazy_harness.core.config import load_config
    from lazy_harness.core.paths import config_file
    from lazy_harness.hooks.signal_gaps import gaps_for_profile

    _write_config(home_dir, {"session_stop": HookEventConfig(scripts=["stop-verify-guard"])})
    cfg = load_config(config_file())

    (gap,) = gaps_for_profile(cfg, "p1")
    assert gap.hook == "stop-verify-guard"
    assert gap.missing == (Signal.GOAL_STATUS,)
    # The distinction the dataclass exists to carry: this one is closed by
    # extending a reader, not by writing one.
    assert gap.has_reader is True


def test_doctor_reports_goal_status_against_the_reader_not_its_absence(
    home_dir: Path,
) -> None:
    from lazy_harness.cli.main import cli

    _write_config(home_dir, {"session_stop": HookEventConfig(scripts=["stop-verify-guard"])})
    doctor = CliRunner().invoke(cli, ["doctor"])

    section = _flat_hook_signals(doctor.output)
    assert "stop-verify-guard" in section
    assert "goal_status" in section
    assert "codex's TranscriptReader does not deliver it" in section
    assert "has no TranscriptReader" not in section
