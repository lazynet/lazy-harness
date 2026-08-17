"""Atomic deep-merge of a TOML block into an existing config.toml.

Writes through `tomlkit` for the same reason `core.config.save_config` does:
the config is hand-maintained and version-controlled, so a wizard run must
change the block it was asked to change and nothing else. `tomli_w` emits no
comments and re-serialises every value it is handed, so `lh config <feature>
--init` used to strip the file's rationale and reformat unrelated sections.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit

from lazy_harness.core.config import HarnessConfig, atomic_write_text

# The version `lh init` writes; a wizard creating the file must match it.
HARNESS_VERSION = HarnessConfig().version


def _apply(doc: Any, overlay: dict[str, Any]) -> None:
    """Apply `overlay` onto a tomlkit document in place.

    A key whose value already matches is left alone: tomlkit re-serialises
    whatever it is assigned, so reassigning an unchanged value would rewrite
    an inline array as a multi-line one and churn the diff.
    """
    for key, value in overlay.items():
        current = doc.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            _apply(doc[key], value)
        elif current != value:
            doc[key] = value


def merge_into_config(config_path: Path, new_block: dict[str, Any]) -> None:
    """Read `config_path` (TOML), merge `new_block` into it, write atomically."""
    if config_path.is_file():
        doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
        # `mkstemp` creates 0600 and `os.replace` carries that onto the target,
        # so a 0644 config would come back 0600 on every wizard run.
        mode = config_path.stat().st_mode & 0o777
    else:
        doc = tomlkit.document()
        # A wizard can run before `lh init`. Writing only its own block would
        # leave no `[harness].version`, and every later `lh` command would then
        # fail to load the file it just created.
        doc["harness"] = {"version": HARNESS_VERSION}
        # `lh init` writes 0644; without this the wizard's file would be 0600,
        # and `save_config` preserves whatever mode it finds, so the two
        # writers of the same file would disagree for its whole life.
        mode = 0o644

    _apply(doc, new_block)

    atomic_write_text(config_path, tomlkit.dumps(doc), default_mode=mode)
