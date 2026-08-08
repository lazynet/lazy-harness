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
