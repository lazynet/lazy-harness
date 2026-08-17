"""Atomic deep-merge of a TOML block into an existing config.toml.

Writes through `tomlkit` for the same reason `core.config.save_config` does:
the config is hand-maintained and version-controlled, so a wizard run must
change the block it was asked to change and nothing else. `tomli_w` emits no
comments and re-serialises every value it is handed, so `lh config <feature>
--init` used to strip the file's rationale and reformat unrelated sections.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import tomlkit


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
        mode: int | None = config_path.stat().st_mode & 0o777
    else:
        doc = tomlkit.document()
        mode = None

    _apply(doc, new_block)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=config_path.parent, prefix=config_path.name + ".")
    tmp_path = Path(tmp)
    try:
        # Close the raw descriptor first and write through a buffered writer: a
        # bare `os.write` can short-write on a full filesystem without raising,
        # and `os.replace` would then install a truncated config over a good
        # one. Closing here also means the descriptor cannot leak when the
        # write fails.
        os.close(fd)
        tmp_path.write_bytes(tomlkit.dumps(doc).encode())
        if mode is not None:
            os.chmod(tmp_path, mode)
        os.replace(tmp_path, config_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
