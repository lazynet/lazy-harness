"""engram-persist against a fake `engram` that parses argv like the real one.

The parse rules come from probing engram 3.5.2 in an isolated store: before a
`--`, every `--token` is a flag, and an unknown one exits 1 with `unknown save
flag: <token>`; after `--` everything is positional; `save` takes exactly two
positionals. Every invocation prints an update banner first, on stderr by
default, as the real binary does.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lazy_harness.knowledge.engram_persist import EngramPersister

_FAKE_ENGRAM = """\
#!{python}
import json, sys
saved_log = {saved_log!r}
always_fail = {always_fail!r}
error_stream = {error_stream!r}
banner_stream = {banner_stream!r}
args = sys.argv[1:]
if args[:1] == ["version"]:
    print("engram 3.5.2")
    sys.exit(0)
banner = "Update available: 3.5.2 -> 3.6.0\\nTo update:\\n  brew update && brew upgrade engram\\n"
err = sys.stdout if error_stream == "stdout" else sys.stderr
(sys.stdout if banner_stream == "stdout" else sys.stderr).write(banner)
if args[:1] != ["save"]:
    err.write("unknown command\\n")
    sys.exit(1)
known = {{"--type", "--project", "--scope", "--topic"}}
positional, flags, i, rest = [], {{}}, 1, False
while i < len(args):
    tok = args[i]
    if rest:
        positional.append(tok)
    elif tok == "--":
        rest = True
    elif tok.startswith("--"):
        if tok not in known:
            err.write("usage: engram save <title> <content> [--type TYPE]\\n")
            err.write("engram: unknown save flag: " + tok + "\\n")
            sys.exit(1)
        i += 1
        flags[tok] = args[i]
    else:
        positional.append(tok)
    i += 1
if len(positional) != 2:
    err.write("engram: save requires exactly two positional arguments\\n")
    sys.exit(1)
title, content = positional
if title in always_fail:
    err.write("engram: refusing " + title + "\\n")
    sys.exit(1)
with open(saved_log, "a") as f:
    f.write(json.dumps({{"title": title, "content": content, "flags": flags}}) + "\\n")
print("Memory saved: #1 " + json.dumps(title))
"""


def _fake_engram(
    tmp_path: Path,
    *,
    always_fail: tuple[str, ...] = (),
    error_stream: str = "stderr",
    banner_stream: str = "stderr",
) -> tuple[Path, Path]:
    saved_log = tmp_path / "saved.jsonl"
    script = tmp_path / "engram"
    script.write_text(
        _FAKE_ENGRAM.format(
            python=sys.executable,
            saved_log=str(saved_log),
            always_fail=list(always_fail),
            error_stream=error_stream,
            banner_stream=banner_stream,
        )
    )
    script.chmod(0o755)
    return script, saved_log


def _persister(tmp_path: Path, engram_bin: Path) -> EngramPersister:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    return EngramPersister(
        memory_dir=memory_dir,
        logs_dir=tmp_path / "logs",
        project_key="tp-caio-g11-2026",
        engram_bin=str(engram_bin),
        cursor_dir=tmp_path / "cursor",
    )


def _seed(memory_dir: Path, entries: list[dict]) -> None:
    (memory_dir / "failures.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))


def _saved_titles(saved_log: Path) -> list[str]:
    if not saved_log.is_file():
        return []
    return [json.loads(line)["title"] for line in saved_log.read_text().splitlines()]


# The shape of the entry that blocked tp-caio-g11-2026's failures.jsonl.
_DASH_ENTRY = {
    "ts": "2026-10-22T17:14:12-03:00",
    "type": "failure",
    "summary": "--delete-branch al mergear #61 borró la base de #62 y GitHub cerró #62",
    "root_cause": "x",
    "project": "tp-caio-g11-2026",
    "tags": ["github", "stacked-prs"],
}


def test_summary_starting_with_dashes_is_saved_as_the_title(tmp_path: Path) -> None:
    engram, saved_log = _fake_engram(tmp_path)
    persister = _persister(tmp_path, engram)
    _seed(persister.memory_dir, [_DASH_ENTRY])

    result = persister.persist_new_entries()

    assert result.saved_failed == 0
    assert _saved_titles(saved_log) == [_DASH_ENTRY["summary"]]
    saved = json.loads(saved_log.read_text().splitlines()[0])
    assert json.loads(saved["content"]) == _DASH_ENTRY
    assert saved["flags"] == {
        "--type": "failure",
        "--project": "tp-caio-g11-2026",
        "--scope": "project",
    }


def _log_records(logs_dir: Path) -> list[str]:
    return (logs_dir / "engram_persist.log").read_text().splitlines()


def test_logged_error_carries_a_failure_printed_on_stdout(tmp_path: Path) -> None:
    engram, _ = _fake_engram(
        tmp_path, always_fail=("doomed",), error_stream="stdout", banner_stream="stderr"
    )
    persister = _persister(tmp_path, engram)
    _seed(persister.memory_dir, [{"ts": "T1", "type": "failure", "summary": "doomed"}])

    persister.persist_new_entries()

    records = _log_records(persister.logs_dir)
    assert len(records) == 1, records
    assert "engram: refusing doomed" in records[0]


def test_logged_error_is_one_line_behind_a_banner_on_the_same_stream(tmp_path: Path) -> None:
    engram, _ = _fake_engram(
        tmp_path, always_fail=("doomed",), error_stream="stderr", banner_stream="stderr"
    )
    persister = _persister(tmp_path, engram)
    _seed(persister.memory_dir, [{"ts": "T1", "type": "failure", "summary": "doomed"}])

    persister.persist_new_entries()

    records = _log_records(persister.logs_dir)
    assert len(records) == 1, records
    assert "engram save returned 1" in records[0]
    assert "engram: refusing doomed" in records[0]


def _quarantine(tmp_path: Path) -> list[dict]:
    path = tmp_path / "cursor" / "engram_quarantine.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def _cursor(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "cursor" / "engram_cursor.json").read_text())


_BAD = {"ts": "T1", "type": "failure", "summary": "poison"}
_GOOD = [{"ts": f"T{i}", "type": "failure", "summary": f"good-{i}"} for i in (2, 3)]


def test_an_always_failing_entry_stops_blocking_the_entries_after_it(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import MAX_ATTEMPTS_PER_ENTRY

    engram, saved_log = _fake_engram(tmp_path, always_fail=("poison",))
    persister = _persister(tmp_path, engram)
    _seed(persister.memory_dir, [_BAD, *_GOOD])

    results = [persister.persist_new_entries() for _ in range(MAX_ATTEMPTS_PER_ENTRY)]

    assert _saved_titles(saved_log) == ["good-2", "good-3"]
    assert [r.quarantined for r in results] == [0] * (MAX_ATTEMPTS_PER_ENTRY - 1) + [1]
    (record,) = _quarantine(tmp_path)
    assert json.loads(record["line"]) == _BAD
    assert record["kind"] == "failure"
    assert record["offset"] == 0
    assert record["attempts"] == MAX_ATTEMPTS_PER_ENTRY
    assert record["project_key"] == "tp-caio-g11-2026"
    assert "engram: refusing poison" in record["error"]
    assert (
        _cursor(tmp_path)["failures_offset"]
        == (persister.memory_dir / "failures.jsonl").stat().st_size
    )


def test_a_failing_entry_is_retried_until_its_attempts_run_out(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import MAX_ATTEMPTS_PER_ENTRY

    engram, saved_log = _fake_engram(tmp_path, always_fail=("poison",))
    persister = _persister(tmp_path, engram)
    _seed(persister.memory_dir, [_BAD, *_GOOD])

    for _ in range(MAX_ATTEMPTS_PER_ENTRY - 1):
        persister.persist_new_entries()

    assert _saved_titles(saved_log) == []
    assert _quarantine(tmp_path) == []
    assert _cursor(tmp_path)["failures_offset"] == 0


def test_attempts_survive_a_run_that_only_saved_the_other_kind(tmp_path: Path) -> None:
    engram, _ = _fake_engram(tmp_path, always_fail=("poison",))
    persister = _persister(tmp_path, engram)
    persister.max_saves_per_run = 1
    _seed(persister.memory_dir, [_BAD])
    persister.persist_new_entries()
    decision = {"ts": "D1", "type": "decision", "summary": "d-1"}
    (persister.memory_dir / "decisions.jsonl").write_text(json.dumps(decision) + "\n")

    # Decisions go first, and the cap stops the run before failures.jsonl.
    result = persister.persist_new_entries()

    assert result.saved_ok == 1
    assert _cursor(tmp_path)["retries"] == {"failure": {"offset": 0, "attempts": 1}}


def test_a_timeout_does_not_use_up_an_attempt(tmp_path: Path) -> None:
    import subprocess
    from unittest.mock import MagicMock, patch

    from lazy_harness.knowledge.engram_persist import MAX_ATTEMPTS_PER_ENTRY

    engram, _ = _fake_engram(tmp_path)
    persister = _persister(tmp_path, engram)
    _seed(persister.memory_dir, [_BAD])

    def fake_run(cmd: list[str], *a: object, **k: object) -> MagicMock:
        if "save" in cmd:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)
        return MagicMock(returncode=0, stdout="engram 3.5.2", stderr="")

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run", side_effect=fake_run):
        for _ in range(MAX_ATTEMPTS_PER_ENTRY + 1):
            persister.persist_new_entries()

    assert _quarantine(tmp_path) == []
    assert _cursor(tmp_path)["failures_offset"] == 0


def test_the_run_metric_counts_quarantined_entries(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import MAX_ATTEMPTS_PER_ENTRY

    engram, _ = _fake_engram(tmp_path, always_fail=("poison",))
    persister = _persister(tmp_path, engram)
    _seed(persister.memory_dir, [_BAD, *_GOOD])

    for _ in range(MAX_ATTEMPTS_PER_ENTRY + 1):
        persister.persist_new_entries()

    metrics = (persister.logs_dir / "engram_persist_metrics.jsonl").read_text().splitlines()
    runs = [json.loads(line) for line in metrics if json.loads(line)["event"] == "run"]
    assert [r["quarantined"] for r in runs][-2:] == [1, 0]
    # The sidecar is the record until someone acts on it, so every run reports it.
    assert [r["quarantined_total"] for r in runs][-2:] == [1, 1]


def test_a_save_clears_the_attempts_left_by_earlier_failures(tmp_path: Path) -> None:
    engram, _ = _fake_engram(tmp_path, always_fail=("poison",))
    persister = _persister(tmp_path, engram)
    _seed(persister.memory_dir, [_BAD])
    persister.persist_new_entries()
    assert _cursor(tmp_path)["retries"] == {"failure": {"offset": 0, "attempts": 1}}

    (tmp_path / "healed").mkdir()
    healed, _ = _fake_engram(tmp_path / "healed")
    persister.engram_bin = str(healed)
    persister.persist_new_entries()

    assert "retries" not in _cursor(tmp_path)
