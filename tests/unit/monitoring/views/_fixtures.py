"""Shared context construction for the view tests."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.config import Config, HarnessConfig
from lazy_harness.core.profiles import ProfileInfo
from lazy_harness.monitoring.views._helpers import StatusContext


def ctx(config_dir: Path, *, name: str = "lazy", exists: bool = True, **kwargs) -> StatusContext:
    return StatusContext(
        cfg=Config(harness=HarnessConfig(version="1")),
        profiles=[
            ProfileInfo(
                name=name, config_dir=config_dir, roots=[], is_default=True, exists=exists
            )
        ],
        **kwargs,
    )
