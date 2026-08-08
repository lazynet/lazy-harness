"""Deterministic coherence check: docs/reference/config.md vs the config dataclasses.

Direction is doc ⊆ code (lax): every `field` cell documented in a config table
must exist on the dataclass that table describes. The reverse is not checked —
several dataclass fields are intentionally undocumented (e.g. `ContextInjectConfig
.qmd_suggest_enabled`, `CompoundLoopConfig.slim_handoff_enabled`).

Doc-section-to-dataclass mapping (see `_SECTION_MAP` below): each TOML section
heading/anchor in the doc is mapped to the one `core.config` dataclass whose
fields the doc claims to describe. The mapping only covers sections that are
backed by an actual typed dataclass with primitive fields. Two doc subsections
are deliberately excluded because they do not map onto a fixed dataclass shape:
`[metrics.sink_options.<name>]` (a free-form `dict[str, Any]` per sink, no fixed
field set) and `[hooks.pre_tool_use].allow_patterns` (read directly from the raw
TOML dict by `pre_tool_use_security.py`, bypassing `HookEventConfig` entirely).

Doc anchor this test depends on: for each mapped section, the first markdown
table (`| Field | ... |` block) that follows its anchor text, and the
backtick-quoted name in that table's first column.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from pathlib import Path

CONFIG_MD = Path(__file__).parent.parent.parent / "docs" / "reference" / "config.md"

_FIELD_CELL = re.compile(r"^\|\s*`(\w+)`\s*\|")


def _table_after(anchor: str, doc_text: str) -> list[str] | None:
    """Return the lines of the first markdown table strictly after `anchor`.

    A markdown table block in this doc is a contiguous run of lines starting
    with "|"; it ends at the first line that does not. Returns None if the
    anchor is not found or no table follows it (conservative: nothing to
    check beats a wrong guess).
    """
    idx = doc_text.find(anchor)
    if idx == -1:
        return None
    rest = doc_text[idx + len(anchor) :]
    lines = rest.splitlines()
    table: list[str] = []
    started = False
    for line in lines:
        if line.startswith("|"):
            started = True
            table.append(line)
        elif started:
            break
    return table or None


def find_missing_fields(anchor: str, doc_text: str, dataclass_type: type) -> list[str]:
    """Return every `field` cell in the table after `anchor` absent from the dataclass."""
    table = _table_after(anchor, doc_text)
    if table is None:
        return []

    known = {f.name for f in fields(dataclass_type)}
    missing: list[str] = []
    for line in table:
        match = _FIELD_CELL.match(line)
        if match is None:
            continue
        name = match.group(1)
        if name not in known:
            missing.append(name)
    return missing


def test_self_test_extractor_flags_only_the_bad_field() -> None:
    @dataclass
    class FakeSection:
        known_good: str = ""

    doc = """
## `[fake]`

Some prose.

| Field | Type | Default | Required | Description |
| --- | --- | --- | --- | --- |
| `known_good` | string | `""` | no | A real field. |
| `known_bad` | string | `""` | no | Not on the dataclass. |
"""

    missing = find_missing_fields("## `[fake]`", doc, FakeSection)

    assert missing == ["known_bad"]


def _section_map() -> list[tuple[str, type]]:
    """Anchor text -> the one dataclass whose primitive fields it documents.

    Order follows the doc top to bottom. Deliberately omits:
    - "## `[memory]`" — no field table of its own, only prose plus the
      `[memory.engram]` sub-table (mapped below).
    - "`[metrics.sink_options.<name>]`" / "`http_remote` options" — a
      free-form per-sink dict, not a fixed dataclass shape.
    - "### `[hooks.pre_tool_use]`" (`allow_patterns`) — read from the raw TOML
      dict by `pre_tool_use_security.py`, not a `HookEventConfig` field.
    - "## Environment variable overrides" — env vars, not a config.toml
      section at all.
    """
    from lazy_harness.core.config import (
        AgentConfig,
        ClassifyRule,
        CompoundLoopConfig,
        ContextInjectConfig,
        EngramConfig,
        HarnessConfig,
        HookEventConfig,
        KnowledgeConfig,
        KnowledgeLearningsConfig,
        KnowledgeSearchConfig,
        KnowledgeSessionsConfig,
        KnowledgeStructureConfig,
        LazyNorthConfig,
        MonitoringConfig,
        ProfileEntry,
        ProfilesConfig,
        SchedulerConfig,
        SchedulerJobConfig,
    )
    from lazy_harness.core.config import MetricsConfig as _MetricsConfig

    return [
        ("## `[harness]`", HarnessConfig),
        ("## `[agent]`", AgentConfig),
        ("## `[profiles]` and `[profiles.<name>]`", ProfilesConfig),
        ("Each `[profiles.<name>]` sub-table:", ProfileEntry),
        ("## `[knowledge]` and sub-tables", KnowledgeConfig),
        ("`[knowledge.sessions]`:", KnowledgeSessionsConfig),
        ("`[knowledge.learnings]`:", KnowledgeLearningsConfig),
        ("`[knowledge.search]`:", KnowledgeSearchConfig),
        ("`[knowledge.structure]` — code-structure layer", KnowledgeStructureConfig),
        ("`[[knowledge.classify_rules]]` (array of tables", ClassifyRule),
        ("`[memory.engram]` — raw episodic memory store", EngramConfig),
        ("## `[monitoring]`", MonitoringConfig),
        ("## `[metrics]`", _MetricsConfig),
        ("## `[scheduler]` and `[scheduler.jobs.<name>]`", SchedulerConfig),
        ("Each `[scheduler.jobs.<name>]` sub-table:", SchedulerJobConfig),
        ("## `[hooks.<event>]`", HookEventConfig),
        ("## `[compound_loop]`", CompoundLoopConfig),
        ("## `[lazynorth]`", LazyNorthConfig),
        ("## `[context_inject]`", ContextInjectConfig),
    ]


def test_anchor_guard_would_catch_a_single_renamed_heading() -> None:
    """A loose `> N` threshold survives a single broken anchor unnoticed.

    Reproduces a real regression: renaming `` ## `[compound_loop]` `` to
    `` ## `[compound-loop]` `` drops that one anchor's table (12
    `CompoundLoopConfig` fields) from `tables_found`, but 18 > 10 is still
    true — the old threshold would have passed with a whole section silently
    unchecked. Only an exact `tables_found == len(section_map)` guard fails
    loudly on this, which is why the real test below uses exact equality.
    """
    doc_text = CONFIG_MD.read_text(encoding="utf-8")
    broken_doc = doc_text.replace("## `[compound_loop]`", "## `[compound-loop]`")
    section_map = _section_map()

    tables_found = sum(1 for anchor, _ in section_map if _table_after(anchor, broken_doc))

    assert tables_found == len(section_map) - 1
    assert tables_found > 10  # the old loose threshold would have missed this


def test_config_reference_fields_exist_on_the_dataclasses() -> None:
    doc_text = CONFIG_MD.read_text(encoding="utf-8")
    section_map = _section_map()

    tables_found = sum(1 for anchor, _ in section_map if _table_after(anchor, doc_text))
    # Guards the anchor set exactly, not just "found more than a handful": a
    # single renamed/broken anchor drops its table silently under a loose
    # `> N` threshold (see test_anchor_guard_would_catch_a_single_renamed_
    # heading above for a reproduction). Exact equality fails loudly instead.
    assert tables_found == len(section_map)

    all_missing: dict[str, list[str]] = {}
    for anchor, dataclass_type in section_map:
        missing = find_missing_fields(anchor, doc_text, dataclass_type)
        if missing:
            all_missing[anchor] = missing

    assert all_missing == {}
