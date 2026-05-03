"""Tests for the compound-loop evaluator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lazy_harness.core.config import CompoundLoopConfig
from lazy_harness.knowledge.compound_loop import (
    build_prompt,
    collect_existing_decisions,
    collect_existing_failures,
    collect_existing_learnings,
    count_user_chars,
    create_task,
    extract_messages,
    is_debounced,
    is_interactive_session,
    last_processed_mtime,
    move_to_done,
    parse_response,
    parse_task,
    persist_results,
    process_task,
    should_queue_task,
    should_reprocess,
    strip_markdown_fences,
)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _interactive_session(tmp_path: Path, name: str = "sess.jsonl") -> Path:
    session = tmp_path / name
    _write_jsonl(
        session,
        [
            {"type": "permission-mode"},
            {"type": "system", "cwd": "/tmp/proj"},
            {"type": "user", "message": {"content": "a" * 250}},
            {"type": "assistant", "message": {"content": "ok"}},
            {"type": "user", "message": {"content": "next step please"}},
            {"type": "assistant", "message": {"content": "done"}},
        ],
    )
    return session


def test_compound_loop_config_default_reprocess_min_growth_seconds_is_120() -> None:
    assert CompoundLoopConfig().reprocess_min_growth_seconds == 120


def test_is_interactive_session_true(tmp_path: Path) -> None:
    session = tmp_path / "s.jsonl"
    _write_jsonl(session, [{"type": "permission-mode"}])
    assert is_interactive_session(session) is True


def test_is_interactive_session_false(tmp_path: Path) -> None:
    session = tmp_path / "s.jsonl"
    _write_jsonl(session, [{"type": "queue-operation"}])
    assert is_interactive_session(session) is False


def test_is_interactive_session_empty_file(tmp_path: Path) -> None:
    session = tmp_path / "s.jsonl"
    session.write_text("")
    assert is_interactive_session(session) is False


def test_count_user_chars_string_content(tmp_path: Path) -> None:
    session = tmp_path / "s.jsonl"
    _write_jsonl(
        session,
        [
            {"type": "user", "message": {"content": "hello"}},
            {"type": "user", "message": {"content": "world"}},
            {"type": "assistant", "message": {"content": "ignored"}},
        ],
    )
    assert count_user_chars(session) == 10


def test_count_user_chars_block_content(tmp_path: Path) -> None:
    session = tmp_path / "s.jsonl"
    _write_jsonl(
        session,
        [
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "text", "text": "foo"},
                        {"type": "text", "text": "bar"},
                    ]
                },
            },
        ],
    )
    assert count_user_chars(session) == 6


def test_extract_messages_returns_count_and_text(tmp_path: Path) -> None:
    session = _interactive_session(tmp_path)
    text, count = extract_messages(session)
    assert count == 4
    assert "## User" in text
    assert "## Assistant" in text
    assert "next step please" in text


def test_extract_messages_tail_bounds(tmp_path: Path) -> None:
    session = tmp_path / "s.jsonl"
    records: list[dict[str, Any]] = [{"type": "permission-mode"}]
    for i in range(30):
        records.append({"type": "user", "message": {"content": f"msg{i}"}})
    _write_jsonl(session, records)
    text, count = extract_messages(session, tail=5)
    assert count == 30
    assert "msg29" in text
    assert "msg25" in text
    assert "msg24" not in text


def test_create_and_parse_task(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    task = create_task(
        queue,
        cwd=Path("/tmp/proj"),
        session_jsonl=Path("/tmp/s.jsonl"),
        session_id="abcd1234efgh",
        memory_dir=Path("/tmp/memory"),
    )
    assert task.is_file()
    meta = parse_task(task)
    assert meta["cwd"] == "/tmp/proj"
    assert meta["session_id"] == "abcd1234efgh"
    assert meta["memory_dir"] == "/tmp/memory"
    assert "timestamp" in meta


def test_is_debounced(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    create_task(queue, Path("/tmp"), Path("/tmp/s.jsonl"), "abcd1234", Path("/tmp/m"))
    assert is_debounced(queue, "abcd1234", window_seconds=60) is True
    assert is_debounced(queue, "ffffffff", window_seconds=60) is False


def test_last_processed_mtime_returns_none_when_no_done_task(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    queue.mkdir()
    assert last_processed_mtime(queue, "abcd1234") is None


def test_last_processed_mtime_ignores_pending_tasks(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    create_task(queue, Path("/tmp"), Path("/tmp/s.jsonl"), "abcd1234", Path("/tmp/m"))
    # Task is in queue but not yet in done/
    assert last_processed_mtime(queue, "abcd1234") is None


def test_last_processed_mtime_returns_done_task_mtime(tmp_path: Path) -> None:
    import os

    queue = tmp_path / "queue"
    task = create_task(queue, Path("/tmp"), Path("/tmp/s.jsonl"), "abcd1234", Path("/tmp/m"))
    move_to_done(queue, task)
    done_task = queue / "done" / task.name
    os.utime(done_task, (1_000_000.0, 1_000_000.0))
    assert last_processed_mtime(queue, "abcd1234") == pytest.approx(1_000_000.0)


def test_last_processed_mtime_returns_latest_when_multiple_done(tmp_path: Path) -> None:
    import os

    queue = tmp_path / "queue"
    t1 = create_task(queue, Path("/tmp"), Path("/tmp/s.jsonl"), "abcd1234", Path("/tmp/m"))
    move_to_done(queue, t1)
    os.utime(queue / "done" / t1.name, (1_000.0, 1_000.0))
    t2 = create_task(queue, Path("/tmp"), Path("/tmp/s.jsonl"), "abcd1234", Path("/tmp/m"))
    move_to_done(queue, t2)
    os.utime(queue / "done" / t2.name, (2_000.0, 2_000.0))
    assert last_processed_mtime(queue, "abcd1234") == pytest.approx(2_000.0)


def test_should_reprocess_true_when_never_processed(tmp_path: Path) -> None:
    session = _interactive_session(tmp_path)
    assert should_reprocess(session, last_processed=None, min_growth_seconds=300) is True


def test_should_reprocess_false_when_session_unchanged(tmp_path: Path) -> None:
    import os

    session = _interactive_session(tmp_path)
    os.utime(session, (5_000.0, 5_000.0))
    # Processed at 5_100 → only 100s of silence, under the 300s threshold
    assert should_reprocess(session, last_processed=5_100.0, min_growth_seconds=300) is False


def test_should_reprocess_true_when_session_grew_past_threshold(tmp_path: Path) -> None:
    import os

    session = _interactive_session(tmp_path)
    os.utime(session, (10_000.0, 10_000.0))
    # Processed 400s before current session mtime → past 300s threshold
    assert should_reprocess(session, last_processed=9_600.0, min_growth_seconds=300) is True


def test_should_queue_task_force_bypasses_debounce_and_growth(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    session = _interactive_session(tmp_path)
    # Debounce active: a task was just queued.
    create_task(queue, Path("/tmp"), session, "abcd1234", Path("/tmp/m"))
    assert (
        should_queue_task(
            queue_dir=queue,
            session_jsonl=session,
            session_id="abcd1234",
            debounce_seconds=60,
            min_growth_seconds=120,
            force=True,
        )
        is True
    )


def test_should_queue_task_default_respects_debounce(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    session = _interactive_session(tmp_path)
    create_task(queue, Path("/tmp"), session, "abcd1234", Path("/tmp/m"))
    assert (
        should_queue_task(
            queue_dir=queue,
            session_jsonl=session,
            session_id="abcd1234",
            debounce_seconds=60,
            min_growth_seconds=120,
            force=False,
        )
        is False
    )


def test_should_queue_task_default_respects_growth_gate(tmp_path: Path) -> None:
    import os

    queue = tmp_path / "queue"
    session = _interactive_session(tmp_path)
    os.utime(session, (5_000.0, 5_000.0))
    task = create_task(queue, Path("/tmp"), session, "abcd1234", Path("/tmp/m"))
    move_to_done(queue, task)
    os.utime(queue / "done" / task.name, (4_990.0, 4_990.0))
    assert (
        should_queue_task(
            queue_dir=queue,
            session_jsonl=session,
            session_id="abcd1234",
            debounce_seconds=1,
            min_growth_seconds=120,
            force=False,
        )
        is False
    )


def test_should_queue_task_default_allows_when_all_clear(tmp_path: Path) -> None:
    import os

    queue = tmp_path / "queue"
    session = _interactive_session(tmp_path)
    os.utime(session, (10_000.0, 10_000.0))
    task = create_task(queue, Path("/tmp"), session, "abcd1234", Path("/tmp/m"))
    move_to_done(queue, task)
    os.utime(queue / "done" / task.name, (9_000.0, 9_000.0))
    assert (
        should_queue_task(
            queue_dir=queue,
            session_jsonl=session,
            session_id="abcd1234",
            debounce_seconds=1,
            min_growth_seconds=120,
            force=False,
        )
        is True
    )


def test_should_reprocess_false_when_session_missing(tmp_path: Path) -> None:
    # Defensive: if the JSONL vanished, don't try to reprocess it.
    assert (
        should_reprocess(tmp_path / "nope.jsonl", last_processed=0.0, min_growth_seconds=300)
        is False
    )


def test_collect_existing_decisions_and_failures(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "decisions.jsonl").write_text(
        json.dumps({"summary": "use uv for deps"})
        + "\n"
        + json.dumps({"summary": "trunk-based"})
        + "\n"
    )
    (memory / "failures.jsonl").write_text(json.dumps({"summary": "broken symlink"}) + "\n")
    assert "use uv for deps" in collect_existing_decisions(memory)
    assert "trunk-based" in collect_existing_decisions(memory)
    assert "broken symlink" in collect_existing_failures(memory)


def test_collect_existing_learnings(tmp_path: Path) -> None:
    learnings = tmp_path / "Learnings"
    (learnings / "2026-04").mkdir(parents=True)
    (learnings / "2026-04" / "2026-04-01-foo.md").write_text(
        '---\ntitle: "Use atomic writes in iCloud"\n---\n'
    )
    (learnings / "2026-04" / "2026-04-02-bar.md").write_text(
        '---\ntitle: "Debounce session export"\n---\n'
    )
    # review files should be ignored
    (learnings / "2026-04" / "_review-2026-04.md").write_text('---\ntitle: "Ignored review"\n---\n')
    out = collect_existing_learnings(learnings)
    assert "Use atomic writes in iCloud" in out
    assert "Debounce session export" in out
    assert "Ignored review" not in out


def test_strip_markdown_fences_with_fence() -> None:
    raw = '```json\n{"x": 1}\n```'
    assert strip_markdown_fences(raw) == '{"x": 1}'


def test_strip_markdown_fences_without_fence() -> None:
    assert strip_markdown_fences('{"x": 1}') == '{"x": 1}'


def test_parse_response_valid() -> None:
    data = parse_response('{"decisions": [], "failures": [], "learnings": [], "handoff": []}')
    assert data == {"decisions": [], "failures": [], "learnings": [], "handoff": []}


def test_parse_response_invalid() -> None:
    assert parse_response("not json") is None


def test_parse_response_prose_preamble() -> None:
    raw = 'Sure! Here is the analysis:\n\n{"decisions": [], "failures": [], "learnings": [], "handoff": []}\n\nHope that helps.'
    data = parse_response(raw)
    assert data == {"decisions": [], "failures": [], "learnings": [], "handoff": []}


def test_parse_response_with_nested_object() -> None:
    raw = '{"decisions": [{"summary": "nested {braces} ok"}], "failures": [], "learnings": [], "handoff": []}'
    data = parse_response(raw)
    assert data is not None
    assert data["decisions"][0]["summary"] == "nested {braces} ok"


def test_build_prompt_includes_all_sections() -> None:
    prompt = build_prompt(
        project_name="proj",
        cwd="/tmp/proj",
        session_id="sess1234",
        timestamp="2026-04-12T10:00:00-03:00",
        existing_decisions="- prior decision",
        existing_failures="- prior failure",
        existing_learnings="- prior learning",
        summary="## User\n\nhi",
    )
    assert "proj" in prompt
    assert "sess1234" in prompt
    assert "prior decision" in prompt
    assert "prior failure" in prompt
    assert "prior learning" in prompt
    assert "## User" in prompt
    assert "Output ONLY the JSON object" in prompt


def test_persist_results_writes_everything(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    data = {
        "decisions": [
            {
                "summary": "use atomic writes",
                "context": "iCloud conflicts",
                "alternatives": ["direct open"],
                "rationale": "rename is atomic",
                "tags": ["io"],
            }
        ],
        "failures": [
            {
                "summary": "conflict copy on stop hook",
                "root_cause": "non-atomic write in iCloud",
                "resolution": "tempfile + rename",
                "prevention": "always os.replace for cloud paths",
                "tags": ["hook"],
            }
        ],
        "learnings": [
            {
                "title": "iCloud hates repeated writes",
                "learning": "Use os.replace to avoid conflict copies.",
                "context": "session export hook",
                "scope": "universal",
                "tags": ["io", "cloud"],
            }
        ],
        "handoff": ["port compound-loop to lazy-harness"],
    }
    wrote = persist_results(data, memory, learnings, "proj", "2026-04-12T10:00:00-03:00")
    assert len(wrote) == 4

    decisions = (memory / "decisions.jsonl").read_text().strip().splitlines()
    assert len(decisions) == 1
    assert json.loads(decisions[0])["summary"] == "use atomic writes"

    failures = (memory / "failures.jsonl").read_text().strip().splitlines()
    assert len(failures) == 1
    assert json.loads(failures[0])["prevention"] == "always os.replace for cloud paths"

    learning_files = list((learnings / "2026-04").glob("*.md"))
    assert len(learning_files) == 1
    content = learning_files[0].read_text()
    assert 'title: "iCloud hates repeated writes"' in content
    assert "Use os.replace" in content

    handoff = (memory / "handoff.md").read_text()
    assert "port compound-loop" in handoff


def test_persist_results_writes_handoff_frontmatter(tmp_path: Path) -> None:
    import os

    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    session = _interactive_session(tmp_path)
    os.utime(session, (12_345.0, 12_345.0))
    data = {"decisions": [], "failures": [], "learnings": [], "handoff": ["do X"]}
    persist_results(
        data,
        memory,
        learnings,
        "proj",
        "2026-04-12T10:00:00-03:00",
        session_id="abcd1234-deadbeef",
        session_jsonl=session,
    )
    text = (memory / "handoff.md").read_text()
    assert text.startswith("---\n")
    assert "session_id: abcd1234-deadbeef" in text
    assert "written_at: 2026-04-12T10:00:00-03:00" in text
    assert "source_mtime: 12345" in text
    assert "do X" in text


def test_persist_results_removes_stale_handoff(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    handoff = memory / "handoff.md"
    handoff.write_text("old content")
    persist_results(
        {"decisions": [], "failures": [], "learnings": [], "handoff": []},
        memory,
        tmp_path / "Learnings",
        "proj",
        "2026-04-12T10:00:00-03:00",
    )
    assert not handoff.exists()


def test_persist_results_skips_duplicate_learning(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    data = {
        "decisions": [],
        "failures": [],
        "learnings": [
            {"title": "Same thing", "learning": "first", "context": "", "scope": "universal"}
        ],
        "handoff": [],
    }
    persist_results(data, memory, learnings, "proj", "2026-04-12T10:00:00-03:00")
    files = list((learnings / "2026-04").glob("*.md"))
    assert len(files) == 1
    first_content = files[0].read_text()

    data["learnings"][0]["learning"] = "second (should be ignored)"
    persist_results(data, memory, learnings, "proj", "2026-04-12T10:00:00-03:00")
    files = list((learnings / "2026-04").glob("*.md"))
    assert len(files) == 1
    assert files[0].read_text() == first_content


def _cfg(**kwargs: Any) -> CompoundLoopConfig:
    return CompoundLoopConfig(
        enabled=True,
        min_messages=4,
        min_user_chars=200,
        debounce_seconds=60,
        timeout_seconds=120,
        **kwargs,
    )


def test_process_task_skips_missing_session(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    task = create_task(queue, Path("/tmp"), tmp_path / "nope.jsonl", "abcd1234", memory)
    outcome = process_task(task, _cfg(), learnings, invoke=lambda *a, **kw: None)
    assert not outcome.was_processed
    assert "not found" in outcome.skipped


def test_process_task_skips_non_interactive(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    session = tmp_path / "s.jsonl"
    _write_jsonl(session, [{"type": "queue-operation"}])
    task = create_task(queue, Path("/tmp"), session, "abcd1234", memory)
    outcome = process_task(task, _cfg(), learnings, invoke=lambda *a, **kw: None)
    assert "non-interactive" in outcome.skipped


def test_process_task_skips_below_min_chars(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    session = tmp_path / "s.jsonl"
    _write_jsonl(
        session,
        [
            {"type": "permission-mode"},
            {"type": "user", "message": {"content": "hi"}},
            {"type": "assistant", "message": {"content": "ok"}},
            {"type": "user", "message": {"content": "hey"}},
            {"type": "assistant", "message": {"content": "yes"}},
        ],
    )
    task = create_task(queue, Path("/tmp"), session, "abcd1234", memory)
    outcome = process_task(task, _cfg(), learnings, invoke=lambda *a, **kw: None)
    assert "user chars" in outcome.skipped


def test_process_task_calls_invoke_and_persists(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    session = _interactive_session(tmp_path)
    task = create_task(queue, Path("/tmp/proj"), session, "abcd1234efgh", memory)

    captured: dict[str, Any] = {}

    def fake_invoke(prompt: str, model: str, timeout: int) -> str:
        captured["prompt"] = prompt
        captured["model"] = model
        return json.dumps(
            {
                "decisions": [],
                "failures": [],
                "learnings": [
                    {
                        "title": "atomic rename saves your sync folder",
                        "learning": "os.replace is atomic on same fs.",
                        "context": "cloud",
                        "scope": "universal",
                    }
                ],
                "handoff": [],
            }
        )

    outcome = process_task(task, _cfg(model="test-model"), learnings, invoke=fake_invoke)
    assert outcome.was_processed
    assert captured["model"] == "test-model"
    assert "Session conversation" in captured["prompt"]
    learning_files = list(learnings.rglob("*.md"))
    assert len(learning_files) == 1


def test_process_task_skips_on_invoke_failure(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    session = _interactive_session(tmp_path)
    task = create_task(queue, Path("/tmp/proj"), session, "abcd1234", memory)
    outcome = process_task(task, _cfg(), learnings, invoke=lambda *a, **kw: None)
    assert "empty" in outcome.skipped


def test_process_task_skips_on_bad_json(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    session = _interactive_session(tmp_path)
    task = create_task(queue, Path("/tmp/proj"), session, "abcd1234", memory)
    outcome = process_task(task, _cfg(), learnings, invoke=lambda *a, **kw: "not json at all")
    assert "JSON parse failed" in outcome.skipped


def test_atomic_write_does_not_leave_tempfile(tmp_path: Path) -> None:
    # Indirectly verified via persist_results: the final dir should not
    # contain any .tmp files after a successful write.
    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    data = {
        "decisions": [],
        "failures": [],
        "learnings": [{"title": "t", "learning": "l", "context": "", "scope": "universal"}],
        "handoff": ["do the thing"],
    }
    persist_results(data, memory, learnings, "proj", "2026-04-12T10:00:00-03:00")
    assert not list(memory.glob(".*.tmp"))
    assert not list(learnings.rglob(".*.tmp"))


# --- ADR-021: async response grading ----------------------------------------


def test_compound_loop_config_defaults_for_grading() -> None:
    cfg = CompoundLoopConfig()
    assert cfg.grading_enabled is True
    assert cfg.lazymind_dir is None


def test_build_prompt_includes_grade_schema_block() -> None:
    prompt = build_prompt(
        project_name="proj",
        cwd="/tmp/proj",
        session_id="sess1234",
        timestamp="2026-05-02T10:00:00-03:00",
        existing_decisions="",
        existing_failures="",
        existing_learnings="",
        summary="## User\n\nhi",
    )
    assert '"grade"' in prompt
    assert '"quality"' in prompt
    for tag in ("excellent", "good", "acceptable", "poor"):
        assert tag in prompt
    for issue in (
        "incomplete",
        "hallucination",
        "tool_misuse",
        "missed_context",
        "wrong_approach",
        "inefficient",
    ):
        assert issue in prompt


def test_persist_results_writes_grades_jsonl_when_grade_present(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    data = {
        "decisions": [],
        "failures": [],
        "learnings": [],
        "handoff": [],
        "grade": {
            "quality": "acceptable",
            "issues": ["inefficient"],
            "reasoning": "Got there but ran ruff three times.",
            "confidence": 0.8,
        },
    }
    wrote = persist_results(
        data,
        memory,
        learnings,
        "proj",
        "2026-05-02T10:00:00-03:00",
        session_id="abcd1234",
    )
    assert any(s.startswith("grade:") for s in wrote)
    grades_file = memory / "grades.jsonl"
    assert grades_file.is_file()
    line = json.loads(grades_file.read_text().strip().splitlines()[0])
    assert line["type"] == "grade"
    assert line["quality"] == "acceptable"
    assert line["issues"] == ["inefficient"]
    assert line["confidence"] == 0.8
    assert line["session_id"] == "abcd1234"
    assert line["project"] == "proj"


def test_persist_results_without_grade_field_does_not_create_grades_jsonl(
    tmp_path: Path,
) -> None:
    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    data = {"decisions": [], "failures": [], "learnings": [], "handoff": []}
    persist_results(data, memory, learnings, "proj", "2026-05-02T10:00:00-03:00")
    assert not (memory / "grades.jsonl").exists()


def _build_lazymind(tmp_path: Path, prj_names: list[str]) -> Path:
    lazymind = tmp_path / "LazyMind"
    projects = lazymind / "1-Projects"
    projects.mkdir(parents=True)
    for name in prj_names:
        prj_dir = projects / f"PRJ-{name}"
        prj_dir.mkdir()
        (prj_dir / f"PRJ-{name}.md").write_text(
            f"---\ntype: project\n---\n# PRJ-{name}\n\n"
            "## Backlog\n\n### Pendiente — Alta prioridad\n\n"
            "- [ ] existing item\n\n### Pendiente — Media prioridad\n\n"
        )
    return lazymind


def test_resolve_prj_md_matches_basename_case_insensitive(tmp_path: Path) -> None:
    from lazy_harness.knowledge.compound_loop import resolve_prj_md

    lazymind = _build_lazymind(tmp_path, ["LazyHarness"])
    found = resolve_prj_md("lazy-harness", lazymind)
    assert found is not None
    assert found.name == "PRJ-LazyHarness.md"


def test_resolve_prj_md_strips_known_prefixes(tmp_path: Path) -> None:
    from lazy_harness.knowledge.compound_loop import resolve_prj_md

    lazymind = _build_lazymind(tmp_path, ["Ansible"])
    found = resolve_prj_md("lazy-ansible", lazymind)
    assert found is not None
    assert found.name == "PRJ-Ansible.md"


def test_resolve_prj_md_returns_none_without_match(tmp_path: Path) -> None:
    from lazy_harness.knowledge.compound_loop import resolve_prj_md

    lazymind = _build_lazymind(tmp_path, ["LazyHarness"])
    assert resolve_prj_md("totally-unrelated-repo", lazymind) is None


def test_resolve_prj_md_returns_none_when_dir_missing(tmp_path: Path) -> None:
    from lazy_harness.knowledge.compound_loop import resolve_prj_md

    assert resolve_prj_md("anything", tmp_path / "missing") is None


def test_append_grade_to_prj_backlog_only_when_grade_warrants(tmp_path: Path) -> None:
    from lazy_harness.knowledge.compound_loop import append_grade_to_prj_backlog

    lazymind = _build_lazymind(tmp_path, ["LazyHarness"])
    prj_md = lazymind / "1-Projects" / "PRJ-LazyHarness" / "PRJ-LazyHarness.md"

    appended = append_grade_to_prj_backlog(
        prj_md,
        {"quality": "good", "issues": [], "reasoning": "fine", "confidence": 0.9},
        "2026-05-02",
        "abcd1234",
    )
    assert appended is False
    assert "Session quality regression" not in prj_md.read_text()


def test_append_grade_to_prj_backlog_writes_for_poor_quality(tmp_path: Path) -> None:
    from lazy_harness.knowledge.compound_loop import append_grade_to_prj_backlog

    lazymind = _build_lazymind(tmp_path, ["LazyHarness"])
    prj_md = lazymind / "1-Projects" / "PRJ-LazyHarness" / "PRJ-LazyHarness.md"

    appended = append_grade_to_prj_backlog(
        prj_md,
        {
            "quality": "poor",
            "issues": ["hallucination", "tool_misuse"],
            "reasoning": "Hallucinated a flag.",
            "confidence": 0.85,
        },
        "2026-05-02",
        "abcd1234",
    )
    assert appended is True
    text = prj_md.read_text()
    assert "Session quality regression — Hallucinated a flag." in text
    assert "graded 2026-05-02" in text
    assert "session abcd1234" in text
    assert "hallucination" in text
    # New item must land under Alta prioridad, before Media.
    alta = text.index("Alta prioridad")
    new_item = text.index("Session quality regression")
    media = text.index("Media prioridad")
    assert alta < new_item < media


def test_append_grade_to_prj_backlog_writes_for_acceptable_with_issues(
    tmp_path: Path,
) -> None:
    from lazy_harness.knowledge.compound_loop import append_grade_to_prj_backlog

    lazymind = _build_lazymind(tmp_path, ["LazyHarness"])
    prj_md = lazymind / "1-Projects" / "PRJ-LazyHarness" / "PRJ-LazyHarness.md"

    appended = append_grade_to_prj_backlog(
        prj_md,
        {
            "quality": "acceptable",
            "issues": ["inefficient"],
            "reasoning": "Avoidable cost.",
            "confidence": 0.7,
        },
        "2026-05-02",
        "abcd1234",
    )
    assert appended is True


def test_append_grade_to_prj_backlog_skips_acceptable_without_issues(
    tmp_path: Path,
) -> None:
    from lazy_harness.knowledge.compound_loop import append_grade_to_prj_backlog

    lazymind = _build_lazymind(tmp_path, ["LazyHarness"])
    prj_md = lazymind / "1-Projects" / "PRJ-LazyHarness" / "PRJ-LazyHarness.md"

    appended = append_grade_to_prj_backlog(
        prj_md,
        {"quality": "acceptable", "issues": [], "reasoning": "ok", "confidence": 0.6},
        "2026-05-02",
        "abcd1234",
    )
    assert appended is False


def test_append_grade_to_prj_backlog_returns_false_when_section_missing(
    tmp_path: Path,
) -> None:
    from lazy_harness.knowledge.compound_loop import append_grade_to_prj_backlog

    prj_md = tmp_path / "PRJ-X.md"
    prj_md.write_text("# PRJ-X\n\nNo backlog here.\n")
    appended = append_grade_to_prj_backlog(
        prj_md,
        {
            "quality": "poor",
            "issues": ["incomplete"],
            "reasoning": "stopped early",
            "confidence": 0.9,
        },
        "2026-05-02",
        "abcd1234",
    )
    assert appended is False


def test_process_task_persists_grade_and_appends_backlog(tmp_path: Path) -> None:
    queue = tmp_path / "queue"
    memory = tmp_path / "memory"
    learnings = tmp_path / "Learnings"
    lazymind = _build_lazymind(tmp_path, ["LazyHarness"])
    prj_md = lazymind / "1-Projects" / "PRJ-LazyHarness" / "PRJ-LazyHarness.md"

    session = _interactive_session(tmp_path)
    cwd = Path("/tmp/lazy-harness")
    task = create_task(queue, cwd, session, "abcd1234-deadbeef", memory)

    response = json.dumps(
        {
            "decisions": [],
            "failures": [],
            "learnings": [],
            "handoff": [],
            "grade": {
                "quality": "poor",
                "issues": ["hallucination"],
                "reasoning": "Made up a flag.",
                "confidence": 0.9,
            },
        }
    )
    cfg = CompoundLoopConfig(
        enabled=True,
        min_messages=2,
        min_user_chars=100,
        lazymind_dir=str(lazymind),
    )
    outcome = process_task(task, cfg, learnings, invoke=lambda *a, **kw: response)

    assert outcome.was_processed
    assert (memory / "grades.jsonl").is_file()
    assert "Session quality regression" in prj_md.read_text()
