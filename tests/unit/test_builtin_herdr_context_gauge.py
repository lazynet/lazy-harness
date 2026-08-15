"""Unit tests for the `herdr-context-gauge` hook."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from lazy_harness.hooks.builtins import herdr_context_gauge as gauge


def _assistant(
    *, input_tokens: int = 0, cache_read: int = 0, cache_creation: int = 0
) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "usage": {
                "input_tokens": input_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
                "output_tokens": 500,
            }
        },
    }


def _write_transcript(path: Path, entries: list[object]) -> Path:
    lines = [e if isinstance(e, str) else json.dumps(e) for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_gauge_label_is_green_below_the_warn_threshold() -> None:
    assert gauge.gauge_label(94_000) == "🟢 94k"


def test_gauge_label_turns_amber_exactly_at_the_warn_threshold() -> None:
    assert gauge.gauge_label(gauge.WARN_TOKENS) == "🟡 200k"


def test_gauge_label_turns_red_exactly_at_the_rotate_threshold() -> None:
    assert gauge.gauge_label(gauge.ROTATE_TOKENS) == "🔴 400k rotar"


def test_gauge_label_carries_the_rotate_verb_only_when_red() -> None:
    """The verb rides inline on the datum the orchestrator already reads in
    `herdr agent list`, so the action needs no separate rule to be adopted."""
    assert "rotar" not in gauge.gauge_label(gauge.WARN_TOKENS)
    assert "rotar" in gauge.gauge_label(673_400)


def test_gauge_label_floors_sub_thousand_counts() -> None:
    assert gauge.gauge_label(940) == "🟢 <1k"


def test_gauge_label_switches_to_megatokens_past_a_million() -> None:
    assert gauge.gauge_label(1_240_000) == "🔴 1.2M rotar"


def test_context_tokens_sums_the_three_input_channels(tmp_path: Path) -> None:
    transcript = _write_transcript(
        tmp_path / "s.jsonl",
        [_assistant(input_tokens=4, cache_read=660_000, cache_creation=13_400)],
    )

    assert gauge.context_tokens(transcript) == 673_404


def test_context_tokens_reports_the_live_window_not_the_cumulative_spend(
    tmp_path: Path,
) -> None:
    """Every turn re-reads the whole window, so summing turns would report
    hundreds of millions. The gauge wants the last turn's window."""
    transcript = _write_transcript(
        tmp_path / "s.jsonl",
        [_assistant(cache_read=100_000), _assistant(cache_read=250_000)],
    )

    assert gauge.context_tokens(transcript) == 250_000


def test_context_tokens_skips_entries_that_carry_no_usage(tmp_path: Path) -> None:
    transcript = _write_transcript(
        tmp_path / "s.jsonl",
        [
            _assistant(cache_read=250_000),
            {"type": "user", "message": {"content": "hola"}},
            {"type": "assistant", "message": {"model": "claude-opus-5"}},
        ],
    )

    assert gauge.context_tokens(transcript) == 250_000


def test_context_tokens_survives_a_corrupt_line(tmp_path: Path) -> None:
    transcript = _write_transcript(
        tmp_path / "s.jsonl",
        [_assistant(cache_read=250_000), "{not json", _assistant(cache_read=310_000)],
    )

    assert gauge.context_tokens(transcript) == 310_000


def test_context_tokens_is_none_for_a_missing_transcript(tmp_path: Path) -> None:
    assert gauge.context_tokens(tmp_path / "absent.jsonl") is None


def test_context_tokens_is_none_when_no_usage_was_ever_recorded(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path / "s.jsonl", [{"type": "user"}])

    assert gauge.context_tokens(transcript) is None


def test_publish_command_targets_the_pane_under_a_dedicated_source() -> None:
    """A distinct --source keeps this metadata from colliding with the
    `herdr:claude` integration that owns lifecycle reporting."""
    cmd = gauge.publish_command("wS:p16", "🔴 673k rotar")

    assert cmd == [
        "herdr",
        "pane",
        "report-metadata",
        "wS:p16",
        "--source",
        "lh:ctx",
        "--display-agent",
        "🔴 673k rotar",
    ]


def test_clear_command_wipes_the_display_agent_under_the_same_source() -> None:
    """Clearing has to name the same --source that published, or Herdr keeps
    the stale label under the original owner."""
    cmd = gauge.clear_command("wS:p16")

    assert cmd == [
        "herdr",
        "pane",
        "report-metadata",
        "wS:p16",
        "--source",
        "lh:ctx",
        "--clear-display-agent",
    ]


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    *,
    env: dict[str, str],
    runner: object,
) -> None:
    monkeypatch.delenv("HERDR_ENV", raising=False)
    monkeypatch.delenv("HERDR_PANE_ID", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(gauge.subprocess, "run", runner)
    with pytest.raises(SystemExit) as exc:
        gauge.main()
    assert exc.value.code == 0


def _recorder() -> tuple[list[list[str]], object]:
    calls: list[list[str]] = []

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return calls, run


def test_main_publishes_the_gauge_for_a_pane_inside_herdr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = _write_transcript(tmp_path / "s.jsonl", [_assistant(cache_read=673_400)])
    calls, runner = _recorder()

    _run_main(
        monkeypatch,
        {"transcript_path": str(transcript)},
        env={"HERDR_ENV": "1", "HERDR_PANE_ID": "wS:p16"},
        runner=runner,
    )

    assert calls == [gauge.publish_command("wS:p16", "🔴 673k rotar")]


def test_main_is_a_no_op_outside_herdr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    transcript = _write_transcript(tmp_path / "s.jsonl", [_assistant(cache_read=673_400)])
    calls, runner = _recorder()

    _run_main(
        monkeypatch,
        {"transcript_path": str(transcript)},
        env={"HERDR_PANE_ID": "wS:p16"},
        runner=runner,
    )

    assert calls == []


def test_main_is_a_no_op_without_a_pane_to_publish_onto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = _write_transcript(tmp_path / "s.jsonl", [_assistant(cache_read=673_400)])
    calls, runner = _recorder()

    _run_main(
        monkeypatch,
        {"transcript_path": str(transcript)},
        env={"HERDR_ENV": "1"},
        runner=runner,
    )

    assert calls == []


def test_main_clears_the_gauge_when_the_transcript_records_no_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No datum means no gauge. Leaving the previous label up would attribute
    another session's window to this one."""
    transcript = _write_transcript(tmp_path / "s.jsonl", [{"type": "user"}])
    calls, runner = _recorder()

    _run_main(
        monkeypatch,
        {"transcript_path": str(transcript)},
        env={"HERDR_ENV": "1", "HERDR_PANE_ID": "wS:p16"},
        runner=runner,
    )

    assert calls == [gauge.clear_command("wS:p16")]


def test_main_clears_the_gauge_when_the_payload_carries_no_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, runner = _recorder()

    _run_main(
        monkeypatch,
        {},
        env={"HERDR_ENV": "1", "HERDR_PANE_ID": "wS:p16"},
        runner=runner,
    )

    assert calls == [gauge.clear_command("wS:p16")]


def test_main_clears_the_gauge_when_a_fresh_session_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Panes outlive the sessions inside them. A startup whose transcript does
    not exist yet must wipe the label the previous session left behind, rather
    than let it stand until the first Stop."""
    calls, runner = _recorder()

    _run_main(
        monkeypatch,
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": str(tmp_path / "not-written-yet.jsonl"),
        },
        env={"HERDR_ENV": "1", "HERDR_PANE_ID": "wS:p16"},
        runner=runner,
    )

    assert calls == [gauge.clear_command("wS:p16")]


def test_main_republishes_the_window_when_a_session_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resume inherits a real window, so the gauge is known before the first
    Stop and there is no reason to blank it."""
    transcript = _write_transcript(tmp_path / "s.jsonl", [_assistant(cache_read=229_000)])
    calls, runner = _recorder()

    _run_main(
        monkeypatch,
        {
            "hook_event_name": "SessionStart",
            "source": "resume",
            "transcript_path": str(transcript),
        },
        env={"HERDR_ENV": "1", "HERDR_PANE_ID": "wS:p16"},
        runner=runner,
    )

    assert calls == [gauge.publish_command("wS:p16", "🟡 229k")]


def test_main_clears_the_gauge_when_the_session_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window dies with the session; the pane does not. Without this the
    label survives into whatever runs in the pane next."""
    transcript = _write_transcript(tmp_path / "s.jsonl", [_assistant(cache_read=673_400)])
    calls, runner = _recorder()

    _run_main(
        monkeypatch,
        {"hook_event_name": "SessionEnd", "transcript_path": str(transcript)},
        env={"HERDR_ENV": "1", "HERDR_PANE_ID": "wS:p16"},
        runner=runner,
    )

    assert calls == [gauge.clear_command("wS:p16")]


def test_main_is_a_no_op_on_session_end_outside_herdr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The environment guards precede the event dispatch, so a teardown outside
    Herdr still shells out to nothing."""
    transcript = _write_transcript(tmp_path / "s.jsonl", [_assistant(cache_read=673_400)])
    calls, runner = _recorder()

    _run_main(
        monkeypatch,
        {"hook_event_name": "SessionEnd", "transcript_path": str(transcript)},
        env={"HERDR_PANE_ID": "wS:p16"},
        runner=runner,
    )

    assert calls == []


def test_main_exits_zero_when_the_herdr_binary_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unhandled OSError here would escape into the Stop chain and take the
    agent's turn down with it."""
    transcript = _write_transcript(tmp_path / "s.jsonl", [_assistant(cache_read=673_400)])

    def explode(cmd: list[str], **kwargs: object) -> None:
        raise OSError("herdr: command not found")

    _run_main(
        monkeypatch,
        {"transcript_path": str(transcript)},
        env={"HERDR_ENV": "1", "HERDR_PANE_ID": "wS:p16"},
        runner=explode,
    )


def test_main_exits_zero_when_herdr_hangs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    transcript = _write_transcript(tmp_path / "s.jsonl", [_assistant(cache_read=673_400)])

    def stall(cmd: list[str], **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd, 5)

    _run_main(
        monkeypatch,
        {"transcript_path": str(transcript)},
        env={"HERDR_ENV": "1", "HERDR_PANE_ID": "wS:p16"},
        runner=stall,
    )
