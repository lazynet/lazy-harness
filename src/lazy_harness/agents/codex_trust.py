"""Which of a Codex profile's deployed hooks the agent will actually run.

Codex refuses to run a hook it has not been shown in its own review screen, and
the refusal is **silent**: nothing is printed, no `hook:` line appears, the guard
simply does not fire. `lh deploy` cannot close that. `HookTrustStatus::Managed`
skips trust entirely, but only for the `System`, `Mdm` and `EnterpriseManaged`
config layers (`discovery.rs:823-838` @ `6b9826e`), and the `User` layer deploy
writes to is explicitly not one of them. The design therefore takes the option
whose failure mode is visible: deploy untrusted, the user approves once in the
TUI, and this module reads the record back.

**It reports strictly less than Codex knows, deliberately.** Codex decides a
hook's status by *comparing* the persisted hash with one it recomputes:

    Some(trusted_hash) if trusted_hash == current_hash => Trusted,
    Some(_)                                            => Modified,
    None                                               => Untrusted,

Computing `current_hash` means reimplementing Codex's TOML normalisation and its
version hash — silently wrong on any upstream change to either, with no signal
until the hooks stop firing. That is the one thing the design declines to do. So
reading a `trusted_hash` back establishes that a hash **was stored** and nothing
whatever about whether it still matches. `unknown` is that state named. Calling
it `trusted` on the strength of a hash's mere presence is precisely the
inference this module exists to stop making.

The third state needs no Codex internals, and it is the useful one: the trust
key is position-scoped, so a redeploy that reorders or drops a group leaves
`[hooks.state]` entries keyed on handlers `hooks.json` no longer declares.
Those `orphaned` entries are the harness's own evidence that it changed a
declaration since the user last approved it.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.core.config import Config

_STATE_SECTION = "hooks"
_STATE_TABLE = "state"
_TRUSTED_HASH = "trusted_hash"

RETRUST_INSTRUCTION = (
    "Codex will not run a hook it has not approved, and says nothing when it "
    "skips one. Approve them in Codex's own review screen — `lh deploy` cannot: "
    "the User config layer it writes to is never Managed."
)
"""The one sentence both `lh doctor` and `lh deploy` print about hook trust.

`lh doctor` prints it once, as a standing footer under the Codex hook trust
section. `lh deploy` prints it whenever it changes a hook declaration — the
moment described in the design (`specs/designs/2026-09-13-multi-agent-harness-
design.md:825-846`) as the point a stored hash becomes known-stale. One string,
imported by both, so the two callers cannot drift onto different wording for
the same instruction.
"""

TRUST_STALE_VERDICT = (
    "the harness changed this hook's declaration since it last deployed, so "
    "any stored hash is known to be out of date."
)
"""The design table's `trust stale` row (specs/designs/2026-09-13-multi-agent-
harness-design.md:825-846), verbatim. `lh deploy` prints it the moment it
changes a declaration; `lh doctor` prints the same wording once it can derive
`stale` from the deploy snapshot — one verdict, one sentence, both callers.
"""


@dataclass(frozen=True)
class CodexHookTrust:
    """One Codex profile's hook-trust record, as far as it can be established.

    `untrusted` and `unknown` are both lists of human labels, not of keys: the
    key is an absolute path plus three indices and says nothing to a reader. The
    label names the canonical event and the group, which is what the user
    recognises in Codex's own review screen.

    `unreadable` is non-empty only when nothing could be established at all —
    `config.toml` missing or unparseable — and then every other field is empty.
    Reporting "0 untrusted" over a file that could not be read would be the
    worst of the three outcomes: it looks like the good one.

    `stale` is a subset of what a stored-hash reading alone would call
    `unknown`: the design's third row, established from the harness's own
    deploy snapshot rather than from anything Codex reports (see
    `_stale_labels`). A key never appears in both.
    """

    profile: str
    hooks_file: Path
    config_file: Path
    untrusted: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()
    orphaned: tuple[str, ...] = ()
    ignored_events: tuple[str, ...] = ()
    unreadable: str = ""

    @property
    def declared(self) -> int:
        return len(self.untrusted) + len(self.unknown) + len(self.stale)


def _stored_hashes(config_raw: str) -> dict[str, str]:
    """`[hooks.state.<key>].trusted_hash`, flattened to `{key: hash}`.

    Every level is type-guarded rather than indexed: this file is the user's and
    Codex's, a hand edit can put a string where a table belongs, and a `lh
    doctor` that raises on it reports nothing about the other twelve sections it
    was going to check.
    """
    document = tomllib.loads(config_raw)
    hooks = document.get(_STATE_SECTION)
    state = hooks.get(_STATE_TABLE) if isinstance(hooks, dict) else None
    if not isinstance(state, dict):
        return {}
    stored: dict[str, str] = {}
    for key, entry in state.items():
        if isinstance(entry, dict) and isinstance(entry.get(_TRUSTED_HASH), str):
            stored[key] = entry[_TRUSTED_HASH]
    return stored


def trust_for_profile(cfg: Config, profile: str) -> CodexHookTrust | None:
    """This profile's trust record, or `None` when there is nothing to report.

    `None` for a profile that does not run Codex and for one whose `hooks.json`
    is absent — a profile with no deployed hooks has no trust question, and a
    line saying so on every `lh doctor` would train the reader past the line
    that matters.
    """
    from lazy_harness.agents.codex import CodexAdapter, trust_keys
    from lazy_harness.agents.registry import agent_for_profile
    from lazy_harness.core.paths import expand_path

    adapter = agent_for_profile(cfg, profile)
    if not isinstance(adapter, CodexAdapter):
        return None

    entry = cfg.profiles.items.get(profile)
    if entry is None or not entry.config_dir:
        return None
    config_dir = expand_path(entry.config_dir)
    hooks_file, config_file = (config_dir / name for name in adapter.config_targets())
    if not hooks_file.is_file():
        return None

    try:
        raw = hooks_file.read_text()
    except OSError as exc:
        return CodexHookTrust(profile, hooks_file, config_file, unreadable=f"{hooks_file}: {exc}")
    declared, ignored = trust_keys(hooks_file, raw)

    try:
        stored = _stored_hashes(config_file.read_text())
    except FileNotFoundError:
        # Not an error state and not a readable one either: Codex writes this
        # file the first time it runs, so its absence means the profile has
        # never been used, and every hook in it is untrusted by definition.
        stored = {}
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return CodexHookTrust(profile, hooks_file, config_file, unreadable=f"{config_file}: {exc}")

    keys = {key for key, _ in declared}
    stale_labels = _stale_labels(hooks_file, raw)
    return CodexHookTrust(
        profile=profile,
        hooks_file=hooks_file,
        config_file=config_file,
        untrusted=tuple(label for key, label in declared if key not in stored),
        unknown=tuple(
            label for key, label in declared if key in stored and label not in stale_labels
        ),
        stale=tuple(label for key, label in declared if key in stored and label in stale_labels),
        orphaned=tuple(
            sorted(k for k in stored if k.startswith(f"{hooks_file}:") and k not in keys)
        ),
        ignored_events=ignored,
    )


def _previous_declaration(hooks_file: Path) -> str | None:
    """`hooks_file`'s content as of the most recent `lh deploy` snapshot.

    `deploy/snapshot.py` records pre-deploy state before every deploy — this is
    therefore the declaration `lh deploy` last overwrote, which is exactly the
    "existing" side `_changed_hook_labels` needs to tell a stale stored hash
    from a merely unknown one, without recomputing anything Codex itself
    computes. `None` when there is nothing to compare against — no deploy has
    ever snapshotted, or this file was absent at every one that has.
    """
    from lazy_harness.core.backups import DEPLOY_NAMESPACE, backups_root, latest_backup_dir
    from lazy_harness.deploy.snapshot import ROLLBACK_LOG_NAME

    snapshot_dir = latest_backup_dir(backups_root(), DEPLOY_NAMESPACE)
    if snapshot_dir is None:
        return None
    try:
        manifest = json.loads((snapshot_dir / ROLLBACK_LOG_NAME).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("path") != str(hooks_file) or entry.get("kind") != "file":
            continue
        content = entry.get("content")
        if not isinstance(content, str):
            return None
        try:
            return (snapshot_dir / content).read_text()
        except OSError:
            return None
    return None


def _stale_labels(hooks_file: Path, raw: str) -> frozenset[str]:
    """Declared labels whose group differs from the last deploy snapshot's copy
    of this file — the design's `trust stale` row, established as the harness's
    own evidence rather than Codex's. Absent a prior snapshot to compare
    against, nothing can be called stale; that remains `unknown`'s job.
    """
    from lazy_harness.agents.codex import _changed_hook_labels

    previous = _previous_declaration(hooks_file)
    if previous is None:
        return frozenset()
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return frozenset()
    current_hooks = document.get("hooks") if isinstance(document, dict) else None
    if not isinstance(current_hooks, dict):
        return frozenset()
    return frozenset(_changed_hook_labels(previous, current_hooks))


def collect_codex_trust(cfg: Config) -> list[CodexHookTrust]:
    """`trust_for_profile` over every profile this config declares.

    Narrowed through `selected_profiles` for the same reason `signal_gaps.py`
    is: the profile set one command reasons about is answered in one place.
    """
    from lazy_harness.deploy.engine import selected_profiles

    reports = (trust_for_profile(cfg, profile) for profile in selected_profiles(cfg, None))
    return [report for report in reports if report is not None]
