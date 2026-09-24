"""Session consumers use the active adapter's declared layout."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


class ThreadsAgent:
    def session_dirs(self) -> dict[str, str]:
        return {"sessions": "threads"}


class NoSessionsAgent:
    pass


def test_exec_billing_reads_the_adapter_session_directory(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli.exec_cmd import _bill_from_transcript
    from lazy_harness.monitoring import collector

    seen: list[Path] = []

    def cost(root, session_id, pricing):
        seen.append(root)
        return SimpleNamespace(
            cost_usd=1.0,
            prompt_tokens=1,
            output_tokens=2,
            cache_creation_tokens=0,
            cache_read_tokens=0,
        )

    monkeypatch.setattr(collector, "session_cost_from_disk", cost)
    envelope: dict = {}
    _bill_from_transcript(envelope, ThreadsAgent(), tmp_path, "session", {})
    assert seen == [tmp_path / "threads"]


def test_exec_billing_skips_an_adapter_without_sessions(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli.exec_cmd import _bill_from_transcript
    from lazy_harness.monitoring import collector

    seen: list[Path] = []
    monkeypatch.setattr(collector, "session_cost_from_disk", lambda root, *_: seen.append(root))
    _bill_from_transcript({}, NoSessionsAgent(), tmp_path, "session", {})
    assert seen == []


def test_project_move_uses_each_adapter_layout(tmp_path: Path) -> None:
    from lazy_harness.core.move_projects import list_projects, move_project

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    project = src / "threads" / "encoded"
    project.mkdir(parents=True)
    (project / "session.jsonl").write_text("{}\n")

    assert list_projects(src, ThreadsAgent()) == ["encoded"]
    result = move_project(src, dst, "encoded", ThreadsAgent(), ThreadsAgent())
    assert result.status == "moved"
    assert (dst / "threads" / "encoded" / "session.jsonl").is_file()


def test_project_move_skips_an_adapter_without_sessions(tmp_path: Path) -> None:
    from lazy_harness.core.move_projects import list_projects, move_project

    project = tmp_path / "src" / "projects" / "encoded"
    project.mkdir(parents=True)
    assert list_projects(project.parent.parent, NoSessionsAgent()) == []
    result = move_project(project.parent.parent, tmp_path / "dst", "encoded", NoSessionsAgent())
    assert result.status == "skipped-missing"
    assert project.is_dir()


def test_legacy_memory_uses_each_profile_adapter(tmp_path: Path) -> None:
    from lazy_harness.core.memory_store import legacy_memory_dirs

    codex = tmp_path / "codex"
    memory = codex / "threads" / "encoded" / "memory"
    memory.mkdir(parents=True)
    false_memory = codex / "projects" / "wrong" / "memory"
    false_memory.mkdir(parents=True)

    assert legacy_memory_dirs([(codex, ThreadsAgent()), (tmp_path, NoSessionsAgent())]) == [memory]
