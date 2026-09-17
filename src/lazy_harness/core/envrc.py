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


_EXPORT_LINE = re.compile(r'^export (\w+)="(.*)"$')


def _parse_exports(block: str) -> dict[str, str]:
    """Every `export ENV_VAR="value"` line inside a managed block, as a dict.

    Tolerant of a block written by an older harness that only ever held one
    export (decision 7, 2026-09-13 multi-agent blast radius design) — there is
    nothing version-specific about the line shape itself, only about how many
    of them a block used to carry.
    """
    exports: dict[str, str] = {}
    for line in block.splitlines():
        match = _EXPORT_LINE.match(line.strip())
        if match:
            exports[match.group(1)] = match.group(2)
    return exports


def _build_block(exports: dict[str, str]) -> str:
    """One export per distinct agent claiming the root, ordered by env var name
    so the block is deterministic regardless of which profile wrote last."""
    lines = [BEGIN_MARKER, NOTICE.format(version=__version__)]
    lines.extend(f'export {env_var}="{exports[env_var]}"' for env_var in sorted(exports))
    lines.append(END_MARKER)
    return "\n".join(lines)


def render_envrc(env_var: str, config_dir: Path, existing: str | None = None) -> str:
    """Return the new .envrc content with `env_var` set in the managed block.

    If `existing` is None the file is created from scratch (block + trailing
    newline). If it already contains the markers, the block's other exports
    (one per agent already claiming this root) are preserved and `env_var` is
    added or updated among them — a second profile's write must not erase the
    first's export (D7, specs/backlog.md). Otherwise the block is appended
    after a blank line.
    """
    exports: dict[str, str] = {}
    existing_block = None
    if existing is not None and BEGIN_MARKER in existing and END_MARKER in existing:
        pattern = re.compile(
            re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER),
            re.DOTALL,
        )
        existing_block = pattern.search(existing)
        if existing_block is not None:
            exports = _parse_exports(existing_block.group(0))

    exports[env_var] = str(config_dir)
    block = _build_block(exports)

    if existing is None:
        return block + "\n"
    if existing_block is not None:
        return existing[: existing_block.start()] + block + existing[existing_block.end() :]
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
