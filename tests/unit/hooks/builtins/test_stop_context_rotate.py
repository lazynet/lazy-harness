"""Tests for the non-blocking context-rotation notice.

The gauge already computes a session's context and paints the pane red at
400k, but nothing acts on it: measured over 72h across both profiles, nine
interactive sessions crossed that threshold and none were rotated. This hook
turns the existing signal into a message the operator actually sees, without
blocking the Stop it rides on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.hooks.builtins import stop_context_rotate as hook


def _transcript(tmp_path: Path, *context_totals: int) -> Path:
    """Write a transcript whose assistant turns carry the given context sizes."""
    path = tmp_path / "transcript.jsonl"
    lines = []
    for total in context_totals:
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "usage": {
                            "input_tokens": total,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                        }
                    },
                }
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run(monkeypatch, capsys, payload: dict[str, object]) -> tuple[int, str]:
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc:
        hook.main()
    return int(exc.value.code or 0), capsys.readouterr().out


@pytest.fixture(autouse=True)
def _isolated_stamps(tmp_path, monkeypatch):
    """Keep the once-per-session stamp inside the test's own tmp_path.

    Without this the hook writes into the real temp dir, so a stamp left by one
    run silences the notice in the next one — the suite passed alone and failed
    in full, which is the failure this fixture removes.
    """
    monkeypatch.setattr(hook, "stamp_dir", lambda: tmp_path / "stamps")


def test_quiet_below_the_rotate_threshold(tmp_path, monkeypatch, capsys) -> None:
    """A session under 400k gets no message at all."""
    t = _transcript(tmp_path, 150_000, 380_000)
    code, out = _run(monkeypatch, capsys, {"transcript_path": str(t), "session_id": "s-under"})
    assert code == 0
    assert out.strip() == ""


def test_warns_above_the_rotate_threshold(tmp_path, monkeypatch, capsys) -> None:
    """At or above 400k the hook emits a non-blocking systemMessage."""
    t = _transcript(tmp_path, 150_000, 437_000)
    code, out = _run(monkeypatch, capsys, {"transcript_path": str(t), "session_id": "s-over"})
    assert code == 0

    payload = json.loads(out)
    # Non-blocking: the Stop decision must not be touched.
    assert "decision" not in payload

    # `systemMessage` is a TOP-LEVEL field, sibling to `hookSpecificOutput`,
    # never nested inside it. Verified against the Claude Code 2.1.269 binary,
    # whose hook schema lists it under "Fields:" ("Display a message to the
    # user (all hooks)") while `hookSpecificOutput` accepts exactly four keys:
    # additionalContext, permissionDecision, permissionDecisionReason and
    # updatedInput. A nested systemMessage is silently discarded, which is a
    # hook that runs, logs, and shows nothing.
    assert "hookSpecificOutput" not in payload, "systemMessage must not be nested"
    msg = payload["systemMessage"]
    assert "437k" in msg
    assert "/compact" in msg and "/clear" in msg


def test_notice_fires_once_per_session(tmp_path, monkeypatch, capsys) -> None:
    """Stop runs every turn; the notice must not repeat all the way down.

    Without this the hook shouts on each of the dozens of Stops a long session
    emits, which is how a warning gets tuned out.
    """
    t = _transcript(tmp_path, 437_000)
    payload = {"transcript_path": str(t), "session_id": "s-once"}

    first_code, first_out = _run(monkeypatch, capsys, payload)
    second_code, second_out = _run(monkeypatch, capsys, payload)

    assert first_code == 0 and first_out.strip() != ""
    assert second_code == 0
    assert second_out.strip() == ""


def test_exits_zero_on_a_missing_transcript(tmp_path, monkeypatch, capsys) -> None:
    """A gauge must never take down the turn it measures."""
    code, out = _run(
        monkeypatch,
        capsys,
        {"transcript_path": str(tmp_path / "nope.jsonl"), "session_id": "s-gone"},
    )
    assert code == 0
    assert out.strip() == ""


@pytest.mark.parametrize("payload", [{}, {"transcript_path": None}, {"transcript_path": 7}])
def test_exits_zero_on_valid_json_wrong_type(payload, monkeypatch, capsys) -> None:
    """Valid JSON carrying the wrong type must be guarded, not just malformed JSON."""
    code, out = _run(monkeypatch, capsys, payload)
    assert code == 0
    assert out.strip() == ""


def test_registered_as_a_builtin_hook() -> None:
    """An implemented hook does not run until it is wired."""
    from lazy_harness.hooks.loader import list_builtin_hooks

    assert "stop-context-rotate" in list_builtin_hooks()


def test_threshold_is_the_gauge_threshold() -> None:
    """Two readers of one question must resolve it the same way.

    The pane turns red at the gauge's ROTATE_TOKENS; a notice that fired at a
    different number would contradict the colour the operator is looking at.
    """
    from lazy_harness.hooks.builtins.herdr_context_gauge import ROTATE_TOKENS

    assert hook.ROTATE_TOKENS is ROTATE_TOKENS
