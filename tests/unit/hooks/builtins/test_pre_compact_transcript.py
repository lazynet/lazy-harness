"""Regression coverage for the nested Claude Code transcript shape."""

import json
from pathlib import Path

import pytest

from lazy_harness.hooks.builtins.pre_compact import build_summary, parse_transcript

FIXTURE = Path(__file__).parents[3] / "fixtures" / "pre_compact_real_transcript.jsonl"


def test_real_transcript_shape_produces_tasks_and_files() -> None:
    messages, files = parse_transcript(FIXTURE)
    summary = build_summary(messages, files)

    assert "## Tasks in progress" in summary
    assert "Review the parser and preserve the current work." in summary
    assert "Finish the transcript shape regression tests." in summary
    assert "Tool output must not become a task." not in summary
    assert "## Files worked on" in summary
    assert "/srv/app/loader.py" in summary
    assert "/srv/app/pre_compact.py" in summary


@pytest.mark.parametrize(
    "record",
    [
        None,
        [],
        {"message": None},
        {"message": []},
        {"message": {"role": "assistant", "content": [{"type": "tool_use", "input": None}]}},
        {"message": {"role": "user", "content": [{"type": "tool_result", "content": "noise"}]}},
        {
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "noise"},
                    {"type": "text", "text": "Do not promote mixed tool output to a human task."},
                ],
            }
        },
    ],
)
def test_non_message_records_are_ignored(tmp_path: Path, record: object) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps(record) + "\n")

    assert parse_transcript(transcript) == ([], [])
