"""Deterministic coherence check: `isolation-gate.sh` against its own header.

The gate's header (line 12) retired the known-gap set outright: step 5 deleted
`BuiltinHookSpec.migrated`, `PRE_RUNNER_AGENT` and both dispatch branches, so the
set "has no source left to be derived from and is gone rather than permanently
empty". A script that says that in its header and then names the known-gap set as
one of the things it derives contradicts itself — and it does so inside an error
message a human only ever reads when the gate is already refusing to guess, which
is the worst place for it.

So the rule is one-directional and cheap: every mention of the known-gap set must
sit in a sentence that says it no longer exists. `known gaps: 0 — the pre-runner
branch and its flag no longer exist` satisfies that; "the known-gap set ... is
DERIVED" does not.
"""

from __future__ import annotations

import re
from pathlib import Path

GATE_SH = Path(__file__).parent.parent.parent / "specs" / "gates" / "f7" / "isolation-gate.sh"

_KNOWN_GAP = re.compile(r"known[- ]gaps?\b", re.IGNORECASE)

# A mention is coherent only if the same line says the set is gone. "no longer
# exist" and "any more" are the two forms the script and its report already use;
# "retired" is allowed so a later rewording is not forced through this test.
_RETIREMENT = re.compile(
    r"no longer exist|any more|is retired|no known-gap set",
    re.IGNORECASE,
)


def mentions_without_retirement(script_text: str) -> list[tuple[int, str]]:
    """Lines naming a known-gap set that do not say it no longer exists."""
    offenders: list[tuple[int, str]] = []
    for number, line in enumerate(script_text.splitlines(), start=1):
        if _KNOWN_GAP.search(line) and not _RETIREMENT.search(line):
            offenders.append((number, line.strip()))
    return offenders


def test_the_gate_never_names_a_known_gap_set_it_can_no_longer_derive() -> None:
    script_text = GATE_SH.read_text(encoding="utf-8")

    # Guards the anchor: if the script stops talking about known gaps entirely
    # this test would pass while checking nothing, so require the header's own
    # retirement note to still be there.
    assert "There is no known-gap set any more" in script_text

    offenders = mentions_without_retirement(script_text)

    assert not offenders, (
        "isolation-gate.sh names a known-gap set its header says is gone: "
        + "; ".join(f"line {n}: {text}" for n, text in offenders)
    )


def test_self_test_extractor_separates_a_retired_mention_from_a_live_one() -> None:
    script = """
# There is no known-gap set any more.
  echo "  the asserted set, the known-gap set and the lane split are all DERIVED"
echo "  known gaps: 0 — the pre-runner branch and its flag no longer exist"
echo "  skipped: 4"
"""
    offenders = mentions_without_retirement(script)

    assert [n for n, _ in offenders] == [3]
    assert "DERIVED" in offenders[0][1]
