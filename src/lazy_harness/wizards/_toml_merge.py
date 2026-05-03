"""Atomic deep-merge of a TOML block into an existing config.toml."""

from __future__ import annotations

import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import tomli_w


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `overlay` into a copy of `base`. Overlay wins on leaves."""
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def merge_into_config(config_path: Path, new_block: dict[str, Any]) -> None:
    """Read `config_path` (TOML), deep-merge `new_block` into it, write atomically."""
    if config_path.is_file():
        existing = tomllib.loads(config_path.read_text())
    else:
        existing = {}

    merged = _deep_merge(existing, new_block)
    serialized = tomli_w.dumps(merged)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=config_path.parent, prefix=config_path.name + ".")
    try:
        os.write(fd, serialized.encode())
        os.close(fd)
        os.replace(tmp, config_path)
    except Exception:
        os.unlink(tmp)
        raise
