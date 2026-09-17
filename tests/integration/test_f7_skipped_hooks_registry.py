"""`SKIPPED_HOOKS` in `isolation-gate.sh` must name only builtins the current
registry still returns.

PR #366 renamed `post-tool-use-sync-claude` to `post-tool-use-sync-system-doc`
and kept the old name only as a resolve-time alias (`hooks/loader.py:284`) —
`list_builtin_hooks()`, which the gate's own coverage assertion reads, does
not return aliases. The rename did not touch `SKIPPED_HOOKS`
(`isolation-gate.sh:299`), so the gate has exited 2 ("harness error:
SKIPPED_HOOKS names 'post-tool-use-sync-claude', which the registry does
not...") since #366 landed. Caught here against the real registry, in
milliseconds, instead of only inside a full temp-tree gate run (~17s).
"""

from __future__ import annotations

import re
from pathlib import Path

from lazy_harness.hooks.loader import list_builtin_hooks

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_SH = REPO_ROOT / "specs" / "gates" / "f7" / "isolation-gate.sh"


def _skipped_hooks() -> list[str]:
    text = GATE_SH.read_text(encoding="utf-8")
    match = re.search(r"^SKIPPED_HOOKS=\((.*?)^\)", text, re.DOTALL | re.MULTILINE)
    assert match, "SKIPPED_HOOKS array not found in isolation-gate.sh"
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def test_every_skipped_hook_is_still_in_the_registry() -> None:
    registered = set(list_builtin_hooks())
    skipped = _skipped_hooks()

    assert skipped, "parsed an empty SKIPPED_HOOKS array — the regex likely broke"
    stale = [name for name in skipped if name not in registered]
    assert not stale, (
        f"SKIPPED_HOOKS names {stale}, which list_builtin_hooks() does not return. "
        "A rename likely dropped the alias from the public registry read; update "
        "the array (and any payload_for() case keyed on the old name) to the new "
        "canonical name."
    )
