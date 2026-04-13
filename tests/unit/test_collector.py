"""Tests for session JSONL collector."""

from __future__ import annotations

import json
from pathlib import Path


def _write_session_jsonl(path: Path, messages: list[dict]) -> None:
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


def test_parse_session_extracts_tokens(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import parse_session

    session_file = tmp_path / "abc12345.jsonl"
    _write_session_jsonl(
        session_file,
        [
            {"type": "user", "content": "hello", "timestamp": "2026-04-12T10:00:00"},
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-6",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 200,
                        "cache_creation_input_tokens": 10,
                    },
                },
                "timestamp": "2026-04-12T10:00:01",
            },
        ],
    )

    results = parse_session(session_file)
    assert len(results) == 1
    r = results[0]
    assert r["model"] == "claude-opus-4-6"
    assert r["input"] == 100
    assert r["output"] == 50
    assert r["cache_read"] == 200
    assert r["cache_create"] == 10
    assert r["session"] == "abc12345"
    assert r["date"] == "2026-04-12"


def test_parse_session_multiple_models(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import parse_session

    session_file = tmp_path / "def67890.jsonl"
    _write_session_jsonl(
        session_file,
        [
            {"type": "user", "content": "hello", "timestamp": "2026-04-12T10:00:00"},
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-6",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
            },
            {
                "type": "assistant",
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {"input_tokens": 200, "output_tokens": 100},
                },
            },
        ],
    )

    results = parse_session(session_file)
    assert len(results) == 2
    models = {r["model"] for r in results}
    assert models == {"claude-opus-4-6", "claude-sonnet-4-6"}


def test_parse_session_empty_file(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import parse_session

    session_file = tmp_path / "empty.jsonl"
    session_file.write_text("")
    results = parse_session(session_file)
    assert results == []


def test_extract_project_name() -> None:
    from lazy_harness.monitoring.collector import extract_project_name

    assert extract_project_name("-Users-foo-repos-my-project") == "my-project"


def test_parse_session_uses_full_uuid_as_session_id(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import parse_session

    uuid = "66056f9a-9981-4554-9ada-06237c999d23"
    session_file = tmp_path / f"{uuid}.jsonl"
    _write_session_jsonl(
        session_file,
        [
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-6",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
                "timestamp": "2026-04-13T10:00:00",
            },
        ],
    )

    results = parse_session(session_file)
    assert results[0]["session"] == uuid
