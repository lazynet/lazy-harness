"""The graph-assist index: a compact derivative of graphify's `graph.json`.

Spec: `specs/designs/2026-09-24-graph-assist-design.md` §3.2. The fixture below
mirrors the shape graphify 0.9.67 writes (`nodes` + `links`); the real-graph
test at the bottom pins the schema against an actual file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from lazy_harness.knowledge import graph_assist as ga


def _node(nid: str, label: str, source_file: str, loc: str, file_type: str = "code") -> dict:
    return {
        "id": nid,
        "label": label,
        "source_file": source_file,
        "source_location": loc,
        "file_type": file_type,
    }


def _link(source: str, target: str, relation: str) -> dict:
    return {"source": source, "target": target, "relation": relation}


GRAPH: dict = {
    "nodes": [
        _node("graphify_py", "graphify.py", "src/pkg/knowledge/graphify.py", "L1"),
        _node("g_check", "check_version()", "src/pkg/knowledge/graphify.py", "L64"),
        _node("e_check", "check_version()", "src/pkg/memory/engram.py", "L59"),
        _node("parse", "parse_version()", "src/pkg/core/versions.py", "L10"),
        _node("doctor", "collect_feature_statuses()", "src/pkg/cli/doctor_cmd.py", "L200"),
        _node("cls", "Engine", "src/pkg/engine.py", "L5"),
        _node("meth", ".run()", "src/pkg/engine.py", "L9"),
        _node("ext_path", "Path", "", ""),
        _node("doc", "Graphify section", "specs/adrs/023-graphify.md", "L3", "document"),
        _node(
            "why", "Probe graphify --version", "src/pkg/knowledge/graphify.py", "L65", "rationale"
        ),
    ],
    "links": [
        _link("graphify_py", "g_check", "contains"),
        _link("g_check", "parse", "calls"),
        _link("e_check", "parse", "calls"),
        _link("doctor", "g_check", "calls"),
        _link("doc", "g_check", "references"),
        _link("why", "g_check", "rationale_for"),
        _link("cls", "meth", "method"),
        _link("doc", "ext_path", "references"),
    ],
}


def test_normalise_lowercases_and_strips_call_parens_and_method_dot() -> None:
    assert ga.normalise("check_version()") == "check_version"
    assert ga.normalise(".run()") == "run"
    assert ga.normalise("Engine") == "engine"


def test_homonyms_keep_every_definition() -> None:
    entries = ga.build_index(GRAPH)

    defs = entries["check_version"]

    assert sorted((d["source_file"], d["source_location"]) for d in defs) == [
        ("src/pkg/knowledge/graphify.py", "L64"),
        ("src/pkg/memory/engram.py", "L59"),
    ]


def test_definition_carries_callers_callees_and_documents() -> None:
    entries = ga.build_index(GRAPH)

    [graphify_def] = [
        d for d in entries["check_version"] if d["source_file"].endswith("graphify.py")
    ]

    assert graphify_def["calls_in"] == ["collect_feature_statuses()"]
    assert graphify_def["calls_out"] == ["parse_version()"]
    assert graphify_def["docs"] == ["specs/adrs/023-graphify.md"]


def test_file_nodes_external_symbols_and_non_code_nodes_are_not_keys() -> None:
    entries = ga.build_index(GRAPH)

    assert "graphify.py" not in entries
    assert "path" not in entries
    assert "graphify section" not in entries
    assert "probe graphify --version" not in entries


def test_lookup_exact_then_unique_qualified_suffix() -> None:
    entries = ga.build_index(GRAPH)

    assert ga.lookup(entries, "check_version") is not None
    assert ga.lookup(entries, "check_version()") is not None
    label, defs = ga.lookup(entries, "graphify.check_version") or ("", [])
    assert label == "check_version()"
    assert [d["source_file"] for d in defs] == ["src/pkg/knowledge/graphify.py"]
    assert ga.lookup(entries, "Engine.run") is not None
    assert ga.lookup(entries, "nowhere.check_version") is None
    assert ga.lookup(entries, "absent_symbol") is None


def test_render_names_every_definition_with_file_and_line() -> None:
    entries = ga.build_index(GRAPH)
    label, defs = ga.lookup(entries, "check_version") or ("", [])

    text = ga.render(label, defs)

    assert text.startswith("Graph: check_version() — 2 definitions")
    assert "src/pkg/knowledge/graphify.py:64" in text
    assert "src/pkg/memory/engram.py:59" in text
    assert "called by: collect_feature_statuses()" in text
    assert "named in: specs/adrs/023-graphify.md" in text
    assert "MANDATORY" not in text


def test_render_caps_definitions_and_counts_the_rest() -> None:
    defs = [
        {
            "label": "main()",
            "source_file": f"src/m{i}.py",
            "source_location": "L1",
            "calls_in": [],
            "calls_out": [],
            "docs": [],
        }
        for i in range(40)
    ]

    text = ga.render("main()", defs)

    assert text.count("\n- ") == 3
    assert "(+37 more)" in text
    assert len(text) <= ga.MAX_CHARS


def test_render_truncates_long_neighbour_lists_to_the_char_budget() -> None:
    many = [f"caller_{i}_with_a_rather_long_name()" for i in range(500)]
    defs = [
        {
            "label": "hub()",
            "source_file": "src/hub.py",
            "source_location": "L1",
            "calls_in": many,
            "calls_out": many,
            "docs": [],
        }
    ]

    assert len(ga.render("hub()", defs)) <= ga.MAX_CHARS


def _repo_with_graph(tmp_path: Path, graph: dict) -> Path:
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text(json.dumps(graph))
    return tmp_path


def test_write_then_load_round_trips(tmp_path: Path) -> None:
    root = _repo_with_graph(tmp_path, GRAPH)

    written = ga.write_index(root)
    loaded = ga.load_index(root)

    assert written == root / "graphify-out" / "cache" / "lh-graph-assist.json"
    assert loaded is not None
    assert len(loaded["check_version"]) == 2


def test_load_rebuilds_an_index_older_than_the_graph(tmp_path: Path) -> None:
    root = _repo_with_graph(tmp_path, {"nodes": [], "links": []})
    ga.write_index(root)
    graph_json = root / "graphify-out" / "graph.json"
    graph_json.write_text(json.dumps(GRAPH))
    # Frozen mtimes, not a sleep: the graph is strictly newer than the index.
    index_mtime = ga.index_path(root).stat().st_mtime
    os.utime(graph_json, (index_mtime + 10, index_mtime + 10))

    loaded = ga.load_index(root)

    assert loaded is not None
    assert "check_version" in loaded


def test_load_builds_a_missing_index(tmp_path: Path) -> None:
    root = _repo_with_graph(tmp_path, GRAPH)

    assert ga.load_index(root) is not None
    assert ga.index_path(root).is_file()


def test_load_gives_up_when_the_build_passes_the_deadline(tmp_path: Path) -> None:
    root = _repo_with_graph(tmp_path, GRAPH)
    ticks = iter([0.0, 1.6])

    loaded = ga.load_index(root, deadline_s=1.5, clock=lambda: next(ticks))

    assert loaded is None
    assert not ga.index_path(root).exists()


def test_load_without_a_graph_is_none(tmp_path: Path) -> None:
    assert ga.load_index(tmp_path) is None


def test_load_with_a_corrupt_graph_is_none(tmp_path: Path) -> None:
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("{not json")

    assert ga.load_index(tmp_path) is None


def _real_graph() -> Path | None:
    """graphify 0.9.67's own output for this repository, from the main checkout."""
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    graph = Path(common).parent / "graphify-out" / "graph.json"
    return graph if graph.is_file() else None


def test_index_from_the_real_graph(tmp_path: Path) -> None:
    graph = _real_graph()
    if graph is None:
        pytest.skip("no graphify-out/graph.json in the main checkout")
    (tmp_path / "graphify-out").mkdir()
    shutil.copy(graph, tmp_path / "graphify-out" / "graph.json")

    entries = ga.load_index(tmp_path, deadline_s=60)

    assert entries is not None
    homonyms = sorted((d["source_file"], d["source_location"]) for d in entries["check_version"])
    assert ("src/lazy_harness/knowledge/graphify.py", "L64") in homonyms
    assert ("src/lazy_harness/memory/engram.py", "L59") in homonyms
    [atomic] = entries["atomic_write_text"]
    assert any(doc.startswith("specs/") for doc in atomic["docs"])
