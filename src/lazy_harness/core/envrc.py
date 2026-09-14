"""Generate / update direnv .envrc files for profile roots.

Each root gets a managed block delimited by markers, so user-authored content
(auth checks, custom env vars) survives regeneration. The block exports the
agent's config-dir env var (e.g. CLAUDE_CONFIG_DIR) so any agent invocation
inside the root automatically picks up the right profile — no launcher needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lazy_harness import __version__

BEGIN_MARKER = "# >>> lazy-harness >>>"
END_MARKER = "# <<< lazy-harness <<<"
# The version is embedded so a reader can tell a block written by an older
# or newer harness apart from one matching the running binary (decision 9,
# 2026-09-13 multi-agent blast radius design). `lazy_harness.core.artifact_version`
# parses it back out with the same "lazy-harness <version>" marker text used
# in the generated system-doc header.
NOTICE = (
    "# Managed by `lh profile envrc` (lazy-harness {version}) — do not edit this block by hand."
)


@dataclass
class EnvrcResult:
    path: Path
    action: str  # "created", "updated", "unchanged"


def _build_block(env_var: str, config_dir: Path) -> str:
    return "\n".join(
        [
            BEGIN_MARKER,
            NOTICE.format(version=__version__),
            f'export {env_var}="{config_dir}"',
            END_MARKER,
        ]
    )


def render_envrc(env_var: str, config_dir: Path, existing: str | None = None) -> str:
    """Return the new .envrc content with the managed block inserted/updated.

    If `existing` is None the file is created from scratch (block + trailing
    newline). If it already contains the markers, only the block is replaced
    in place. Otherwise the block is appended after a blank line.
    """
    block = _build_block(env_var, config_dir)
    if existing is None:
        return block + "\n"
    if BEGIN_MARKER in existing and END_MARKER in existing:
        pattern = re.compile(
            re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER),
            re.DOTALL,
        )
        return pattern.sub(block, existing)
    sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    return existing + sep + block + "\n"


def write_envrc(root: Path, env_var: str, config_dir: Path) -> EnvrcResult:
    """Create or update root/.envrc with the managed block. Idempotent."""
    root.mkdir(parents=True, exist_ok=True)
    envrc = root / ".envrc"
    existing: str | None = None
    if envrc.is_file():
        existing = envrc.read_text()
    new_content = render_envrc(env_var, config_dir, existing)
    if existing is None:
        envrc.write_text(new_content)
        return EnvrcResult(path=envrc, action="created")
    if new_content == existing:
        return EnvrcResult(path=envrc, action="unchanged")
    envrc.write_text(new_content)
    return EnvrcResult(path=envrc, action="updated")
