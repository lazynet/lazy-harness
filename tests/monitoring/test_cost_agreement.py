"""`lh exec` and `lh metrics ingest` must answer "what did this session cost"
with one number.

Two readers price the same transcripts: `session_cost_from_disk`, which the
`lh exec` timeout path uses to fill an envelope it would otherwise report as
free, and `ingest_profile`, which bills the same run into `session_stats`.
They are invoked here on identical input and asserted to agree, rather than
each being checked against a number written by its own test.
"""

from __future__ import annotations

import json
from pathlib import Path

SESSION_ID = "c02bfa9d-ba8e-4f9d-91bd-96df64c7b8ce"


def _assistant(msg_id: str, model: str, *, inp: int, out: int, cache_read: int, c1h: int) -> dict:
    return {
        "type": "assistant",
        "timestamp": "2026-08-31T11:19:00",
        "message": {
            "id": msg_id,
            "model": model,
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": 512 + c1h,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 512,
                    "ephemeral_1h_input_tokens": c1h,
                },
            },
        },
    }


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _build_tree(projects_dir: Path) -> None:
    """One pinned session: two models, subagent turns, and a message id
    repeated across two files so both readers have to dedup it."""
    project = projects_dir / "-private-tmp-scratchpad"
    parent_turn = _assistant(
        "msg_p1", "claude-opus-4-6", inp=73, out=966, cache_read=259_229, c1h=17_850
    )
    _write(
        project / f"{SESSION_ID}.jsonl",
        [
            {"type": "user", "content": "go", "timestamp": "2026-08-31T11:19:00"},
            parent_turn,
            _assistant("msg_p2", "claude-opus-4-7", inp=12, out=340, cache_read=8_000, c1h=0),
        ],
    )
    subagents = project / SESSION_ID / "subagents"
    _write(
        subagents / "agent-alpha.jsonl",
        [_assistant("msg_s1", "claude-opus-4-6", inp=5, out=1_200, cache_read=40_000, c1h=900)],
    )
    _write(
        subagents / "agent-beta.jsonl",
        [
            _assistant("msg_s2", "claude-opus-4-7", inp=9, out=77, cache_read=1_500, c1h=0),
            parent_turn,  # same message.id as the parent's first turn
        ],
    )


def test_exec_and_ingest_price_the_same_session_identically(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import ProfileInfo
    from lazy_harness.monitoring.collector import session_cost_from_disk
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    config_dir = tmp_path / "lazy"
    projects_dir = config_dir / "projects"
    projects_dir.mkdir(parents=True)
    _build_tree(projects_dir)
    pricing = load_pricing()

    from_exec = session_cost_from_disk(projects_dir, SESSION_ID, pricing)

    prof = ProfileInfo(name="lazy", config_dir=config_dir, roots=[], is_default=True, exists=True)
    db = MetricsDB(tmp_path / "metrics.db")
    try:
        ingest_profile(prof, db, pricing)
        rows = db.query_stats(period="all")
    finally:
        db.close()

    assert {r["session"] for r in rows} == {SESSION_ID}
    assert from_exec.cost_usd is not None
    assert from_exec.cost_usd > 0

    assert from_exec.cost_usd == round(sum(r["cost"] for r in rows), 6)
    assert from_exec.output_tokens == sum(r["output"] for r in rows)
    assert from_exec.cache_read_tokens == sum(r["cache_read"] for r in rows)
    assert from_exec.cache_creation_tokens == sum(r["cache_create"] for r in rows)
    assert from_exec.prompt_tokens == sum(
        r["input"] + r["cache_read"] + r["cache_create"] for r in rows
    )
