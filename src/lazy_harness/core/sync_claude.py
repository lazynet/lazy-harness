"""Compatibility shim — re-exports from sync_agent_md.

Renamed in ADR-031. This module will be removed in a future release.
"""

from lazy_harness.core.sync_agent_md import (
    SyncError,  # noqa: F401
    SyncResult,  # noqa: F401
    sync_profiles,  # noqa: F401
)
from lazy_harness.core.sync_agent_md import render_agent_md as render_claude_md  # noqa: F401
