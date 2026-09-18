"""F8's expected sets must name only builtins the registry still returns."""

from __future__ import annotations

import re
from pathlib import Path

from lazy_harness.hooks.loader import list_builtin_hooks

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_SH = REPO_ROOT / "specs" / "gates" / "f8" / "translation-gate.sh"


def _expected_names(array_name: str) -> list[str]:
    text = GATE_SH.read_text(encoding="utf-8")
    match = re.search(rf"^{array_name}=\((.*?)^\)", text, re.DOTALL | re.MULTILINE)
    assert match, f"{array_name} array not found in translation-gate.sh"
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def test_expected_sets_name_only_registered_builtins() -> None:
    registered = set(list_builtin_hooks())
    expected_inert = _expected_names("EXPECTED_INERT")
    expected_live = _expected_names("EXPECTED_LIVE")

    stale = [
        (array_name, name)
        for array_name, names in (
            ("EXPECTED_INERT", expected_inert),
            ("EXPECTED_LIVE", expected_live),
        )
        for name in names
        if name not in registered
    ]
    assert not stale, (
        f"translation-gate.sh expected sets name unregistered builtins: {stale}; "
        "update each stale name at its array line to the canonical registry name"
    )
    assert set(expected_inert).isdisjoint(expected_live), (
        "EXPECTED_INERT and EXPECTED_LIVE must be disjoint"
    )
