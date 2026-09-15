"""Version provenance for deployed managed artifacts (decision 9).

`deploy_hooks` (`deploy/engine.py`), `write_envrc` (`core/envrc.py`) and
`sync_profiles` (`core/sync_agent_md.py`) each stamp the artifact they write
with the lazy-harness version that wrote it — `lh_version` in settings.json,
and a `"lazy-harness <version>"` marker inside the `.envrc` notice and the
generated system-doc header. This module is the one place that reads that
stamp back out and compares it against the running binary, so every caller —
today only `lh doctor` — answers "is this artifact newer than me" the same
way.

Reporting only: a hard refusal on a version mismatch turns a stale artifact
into an unusable machine, which is the failure this decision closes, not the
mismatch itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from lazy_harness.agents.registry import agent_for_profile
from lazy_harness.core.paths import expand_path

if TYPE_CHECKING:
    from lazy_harness.core.config import Config

# Parenthesised so it cannot match `.envrc`'s own `# >>> lazy-harness >>>`
# block delimiter, which also contains the literal words "lazy-harness".
_VERSION_MARKER_RE = re.compile(r"\(lazy-harness ([^)]+)\)")


def parse_version(version: str) -> tuple[int, ...] | None:
    """Parse a release-please `MAJOR.MINOR.PATCH` string into a comparable tuple.

    Returns None for anything that doesn't parse cleanly — an artifact from
    before this field existed, or a hand-edited value — so callers can treat
    "can't tell" distinctly from "not newer".
    """
    parts = version.strip().split(".")
    if not parts or not all(parts):
        return None
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def is_newer(artifact_version: str, installed_version: str) -> bool:
    """Whether `artifact_version` postdates `installed_version`.

    Unparsable input on either side reports False: a check that cannot prove
    a mismatch must not manufacture one.
    """
    artifact = parse_version(artifact_version)
    installed = parse_version(installed_version)
    if artifact is None or installed is None:
        return False
    return artifact > installed


def extract_from_text(content: str) -> str | None:
    """Pull `lh_version` back out of a `.envrc` notice or a generated header."""
    match = _VERSION_MARKER_RE.search(content)
    return match.group(1) if match else None


def extract_from_settings(settings: dict) -> str | None:
    """Pull `lh_version` back out of a parsed settings.json document.

    Read from the document's top level, not from inside `settings["hooks"]`
    — see `deploy_hooks` (`deploy/engine.py`) for why: measurement confirmed
    Claude Code tolerates the unknown key in either position, so that is not
    what decides it. `settings["hooks"]` is a `{event: [entry, ...]}`
    contract, and the version of the document is not a hook entry.
    """
    version = settings.get("lh_version")
    return version if isinstance(version, str) else None


# The managed section's record of which launcher generated this file's hook
# commands. Both ends live in the Claude Code adapter since the merge moved
# there: `ClaudeCodeAdapter._plan_settings` writes it and `_owned_binaries`
# reads it back, each through this module, so the name of the key has one home.
SETTINGS_BINARY_KEY = "lh_harness_binary"


def extract_binary_from_settings(settings: dict) -> str | None:
    """Pull the writing launcher back out of a parsed settings.json document.

    Ownership of a generated hook command is *declared by the artifact*, not
    inferred from the config that happens to be loaded now. Inferring it is
    what broke: the allow-list came from `[profiles.*].harness_binary`, so a
    profile rolled back off `lh-beta` dropped `lh-beta` from the set and read
    the entries its own previous deploy had written as another tool's —
    duplicating every hook on exactly the two movements (beta rollback, beta
    promotion) decision 11 exists to make safe.

    None means the stamp is absent or not a string. Every settings.json written
    before this key existed was written with the default launcher, since no
    released version could emit anything else, so the caller reads None as
    `DEFAULT_HARNESS_BINARY` rather than as "unknown".
    """
    binary = settings.get(SETTINGS_BINARY_KEY)
    return binary if isinstance(binary, str) and binary else None


@dataclass
class ArtifactVersionReport:
    profile: str
    kind: str  # "settings.json", ".envrc", or the agent's system-doc name
    path: Path
    lh_version: str | None


def _settings_report(profile: str, config_dir: Path) -> ArtifactVersionReport | None:
    settings_file = config_dir / "settings.json"
    if not settings_file.is_file():
        return None
    try:
        settings = json.loads(settings_file.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(settings, dict):
        return None
    return ArtifactVersionReport(
        profile=profile,
        kind="settings.json",
        path=settings_file,
        lh_version=extract_from_settings(settings),
    )


def _envrc_reports(profile: str, roots: list[str]) -> list[ArtifactVersionReport]:
    reports = []
    for root in roots:
        envrc = expand_path(root) / ".envrc"
        if envrc.is_file():
            reports.append(
                ArtifactVersionReport(
                    profile=profile,
                    kind=".envrc",
                    path=envrc,
                    lh_version=extract_from_text(envrc.read_text()),
                )
            )
    return reports


def _doc_report(profile: str, profiles_dir: Path, doc_name: str) -> ArtifactVersionReport | None:
    if not doc_name:
        return None
    doc = profiles_dir / profile / doc_name
    if not doc.is_file():
        return None
    return ArtifactVersionReport(
        profile=profile,
        kind=doc_name,
        path=doc,
        lh_version=extract_from_text(doc.read_text()),
    )


def collect_artifact_version_reports(
    cfg: Config, profiles_dir: Path
) -> list[ArtifactVersionReport]:
    """Read the `lh_version` stamp off every deployed artifact this profile owns.

    Only artifacts that exist on disk are reported — a missing settings.json
    or `.envrc` is a deploy-state question other `lh doctor` sections already
    answer, not a version question.

    The agent is resolved per profile via `agent_for_profile`, not once above
    this loop: `[profiles.<name>].agent` can override the global agent, and a
    doc name read off the wrong adapter probes the wrong file — the same
    defect `agent_for_profile` itself was added to fix for deploy.
    """
    reports: list[ArtifactVersionReport] = []
    for name, entry in cfg.profiles.items.items():
        agent = agent_for_profile(cfg, name)
        settings_report = _settings_report(name, expand_path(entry.config_dir))
        if settings_report is not None:
            reports.append(settings_report)
        reports.extend(_envrc_reports(name, entry.roots))
        doc_report = _doc_report(name, profiles_dir, agent.system_doc_name())
        if doc_report is not None:
            reports.append(doc_report)
    return reports
