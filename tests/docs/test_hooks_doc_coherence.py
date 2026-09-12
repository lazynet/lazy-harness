"""Deterministic coherence check: docs/how/hooks.md vs `_BUILTIN_HOOKS`.

This is the one test of the three that checks both directions: `_BUILTIN_HOOKS`
is a small, fixed registry (`src/lazy_harness/hooks/loader.py` line 33), so full
coverage in both directions is cheap and valuable — every documented built-in
must be registered, and every registered built-in must be documented.

Doc anchor this test depends on: the `### \\`<hook-name>\\` — runs on ...`
headings under "## The built-ins" in docs/how/hooks.md.
"""

from __future__ import annotations

import re
from pathlib import Path

HOOKS_MD = Path(__file__).parent.parent.parent / "docs" / "how" / "hooks.md"

_HOOK_HEADING = re.compile(r"^### `([a-z0-9-]+)`", re.MULTILINE)


def _extract_documented_hook_names(doc_text: str) -> set[str]:
    """Pull every `### \\`<name>\\`` heading name out of the doc."""
    return set(_HOOK_HEADING.findall(doc_text))


def diff_hook_names(doc_text: str, registered: set[str]) -> tuple[set[str], set[str]]:
    """Return (documented_but_not_registered, registered_but_not_documented)."""
    documented = _extract_documented_hook_names(doc_text)
    return documented - registered, registered - documented


def test_self_test_extractor_flags_both_directions() -> None:
    doc = """
## The built-ins

### `known-good` — runs on `SomeEvent`

Body.

### `known-bad` — runs on `SomeEvent`

Body.
"""
    doc_only, code_only = diff_hook_names(doc, {"known-good", "code-only-hook"})

    assert doc_only == {"known-bad"}
    assert code_only == {"code-only-hook"}


def test_hooks_doc_matches_builtin_registry() -> None:
    from lazy_harness.hooks.loader import _BUILTIN_HOOKS

    doc_text = HOOKS_MD.read_text(encoding="utf-8")
    documented = _extract_documented_hook_names(doc_text)

    # Guards the anchor: a doc restructure that drops the "### `<name>`" heading
    # shape must fail loudly instead of silently checking nothing.
    assert len(documented) > 0

    doc_only, code_only = diff_hook_names(doc_text, set(_BUILTIN_HOOKS))

    assert doc_only == set()
    assert code_only == set()


_DEFAULTS_ROW = re.compile(
    r"^\|\s*`(session_start|session_stop|session_end|pre_compact|pre_tool_use|post_tool_use)`\s*\|.*$",
    re.MULTILINE,
)
_BACKTICKED = re.compile(r"`([a-z0-9-]+)`")


def hooks_named_in_defaults_rows(doc_text: str) -> dict[str, set[str]]:
    """Per event, the hook names the doc's summary tables claim ship by default.

    The event key itself is the row's first cell, so it is dropped: what is
    wanted is the hook names listed in the remaining cells.
    """
    found: dict[str, set[str]] = {}
    for match in _DEFAULTS_ROW.finditer(doc_text):
        row = match.group(0)
        event = match.group(1)
        names = set(_BACKTICKED.findall(row)) - {event}
        found.setdefault(event, set()).update(names)
    return found


def test_defaults_tables_match_the_derived_default_hooks() -> None:
    """The summary tables must list exactly what DEFAULT_HOOKS ships.

    The heading test above is not enough: a new builtin can be registered,
    documented with its own section, and shipped default-on while these two
    tables still name the old set. That happened with `stop-context-rotate` —
    the code shipped four session_stop hooks and both tables kept saying three,
    and every existing test passed. This closes that direction.
    """
    from lazy_harness.deploy.defaults import DEFAULT_HOOKS

    doc_text = HOOKS_MD.read_text(encoding="utf-8")
    in_tables = hooks_named_in_defaults_rows(doc_text)

    assert in_tables, "defaults tables not found — the row anchor moved"

    for event, shipped in DEFAULT_HOOKS.items():
        documented = in_tables.get(event, set())
        missing = set(shipped) - documented
        assert not missing, f"{event}: tables omit default-on hook(s) {sorted(missing)}"


def test_defaults_row_extractor_reads_names_and_drops_the_event_key() -> None:
    """Guards the anchor: a table restructure must fail loudly, not silently pass."""
    doc = """
| `session_stop` | `Stop` | After every turn | `alpha`, `beta` | Do things |
| `pre_compact` | `PreCompact` | Before compaction | `gamma` | Preserve |
"""
    got = hooks_named_in_defaults_rows(doc)
    # The Claude Code event name (`Stop`, `PreCompact`) is capitalised, so the
    # hook-name pattern skips it and only real hook names come back.
    assert got["session_stop"] == {"alpha", "beta"}
    assert got["pre_compact"] == {"gamma"}
