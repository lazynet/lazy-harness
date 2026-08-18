"""One enumerable surface for everything that can be turned on.

Six kinds of thing are switchable in this framework — tools, hooks, metrics
sinks, the agent, the scheduler backend, the LLM backend — and each was
discovered by reading a different module. Nothing could answer "what can be
enabled here, and what is enabled now" without a person doing the enumeration.

The registry is pure and in-memory. It never reads or writes a file: `state`
takes an injected probe, and `toggle` returns a new `Config` for the caller to
persist. A registry that wrote config would put the config-loss failure behind
two layers instead of one.

See ADR-035 and specs/designs/2026-08-17-capability-registry-design.md.
"""

from __future__ import annotations

import copy
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from lazy_harness.core.config import Config

Probe = Callable[[str], bool]


def which_probe(binary: str) -> bool:
    """Whether `binary` is on PATH. The default, so it is not left untested."""
    return shutil.which(binary) is not None


class Cardinality(StrEnum):
    """How many implementations of a kind can be active at once.

    Kept separate from the dependency axis rather than collapsed into one
    "plugin kind" enum: that produces a three-valued enum where one value is
    secretly a combination of the other two.
    """

    ONE = "one"
    MANY = "many"


class CapabilityState(StrEnum):
    """What a capability is doing right now.

    Two states when there is nothing external to install, four when there is.
    The four-state half is not new logic — it is what `features.py` already
    implements three times over, written once.
    """

    ON = "on"
    OFF = "off"
    ACTIVE = "active"
    DORMANT = "dormant"
    BROKEN = "broken"
    MISSING = "missing"


@dataclass(frozen=True)
class Capability:
    name: str
    kind: str
    cardinality: Cardinality
    config_path: str
    summary: str
    binary: str = ""
    pinned_version: str = ""
    enabled_by_default: bool = False
    install_hint: str = ""


class _Absent:
    """The path is well-formed but this config does not declare it.

    Distinct from a falsy value: `merge_with_defaults` treats an undeclared
    event as "use the defaults" and a declared-but-empty one as an explicit
    opt-out, and the registry has to give the same two answers or `lh doctor`
    and `lh deploy` disagree about whether a hook is on.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<absent>"


ABSENT = _Absent()


def _resolve(cfg: Config, dotted: str, *, owner: str = "") -> object:
    """Walk a dotted path against the loaded `Config`.

    Raises rather than defaulting: a capability naming a key that does not
    exist is a registration bug, and answering `OFF` would hide it behind a
    plausible answer — which is how a config field can promise behaviour it
    never had.

    The error names the capability and the whole path. `Config.hooks` and
    `ProfilesConfig.items` are plain dicts, so a path through either fails on
    `getattr` with a message naming only the key it tried, which says nothing
    about which registration is wrong.
    """
    current: object = cfg
    for part in dotted.split("."):
        # `Config.hooks` and `ProfilesConfig.items` are plain dicts, so a path
        # through either has to be walked by key. A missing key is ABSENT, not
        # an error: the section simply is not declared.
        if isinstance(current, Mapping):
            if part not in current:
                return ABSENT
            current = current[part]
            continue
        try:
            current = getattr(current, part)
        except AttributeError as e:
            where = f"capability {owner!r}: " if owner else ""
            raise AttributeError(f"{where}config path {dotted!r} does not resolve — {e}") from e
    return current


class CapabilityRegistry:
    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}

    def register(self, cap: Capability) -> None:
        if cap.name in self._caps:
            raise ValueError(f"capability {cap.name!r} is already registered")
        self._caps[cap.name] = cap

    def capabilities(self, *, kind: str | None = None) -> list[Capability]:
        caps = list(self._caps.values())
        return [c for c in caps if kind is None or c.kind == kind]

    def get(self, name: str) -> Capability:
        if name not in self._caps:
            raise KeyError(f"no capability registered under {name!r}")
        return self._caps[name]

    def state(self, cap: Capability, cfg: Config, *, probe: Probe = which_probe) -> CapabilityState:
        # An empty path means there is no switch. `knowledge.search` carries
        # only `engine`, so qmd has no on/off key, and inventing one to satisfy
        # the model would be a config schema change disguised as a refactor.
        # Such a capability has two states, not four: it is ACTIVE when present
        # and MISSING when not. It is never BROKEN — that word means "enabled
        # but the binary is gone", and nobody enabled this one.
        if not cap.config_path:
            if not cap.binary:
                raise ValueError(
                    f"capability {cap.name!r} has neither a config switch nor a binary, "
                    "so there is nothing to report on"
                )
            return CapabilityState.ACTIVE if probe(cap.binary) else CapabilityState.MISSING

        value = _resolve(cfg, cap.config_path, owner=cap.name)
        if value is ABSENT:
            # Undeclared, so the framework default decides. This is the rule
            # `merge_with_defaults` applies, and two answers to "is this on"
            # that disagree is how a hook stops running with nothing reporting.
            enabled = cap.enabled_by_default
        elif isinstance(value, (list, tuple, set)):
            # Membership, not truthiness: `bool(["a"])` is True for every
            # capability pointed at that list, so two sinks sharing one path
            # both answered ON — including the one never added to it.
            enabled = cap.name in value
        elif cap.cardinality is Cardinality.ONE and isinstance(value, str):
            # An exclusive choice stores the selected implementation's name.
            # Read with truthiness, `bool("claude-code")` is True for every
            # sibling, so all of them reported enabled at once.
            enabled = value == cap.name
        elif isinstance(value, (bool, str, int, float)) or value is None:
            enabled = bool(value)
        else:
            # Anything else is a section, not a switch — a `Mapping`, or a
            # config dataclass. Listed by what a switch may be rather than by
            # what it may not: `bool(EngramConfig())` is True, so a path that
            # stopped one segment short answered ON for every config.
            raise TypeError(
                f"capability {cap.name!r}: config path {cap.config_path!r} stops on a "
                f"{type(value).__name__}, which names a section rather than a switch"
            )

        if not cap.binary:
            return CapabilityState.ON if enabled else CapabilityState.OFF
        installed = probe(cap.binary)
        if enabled:
            return CapabilityState.ACTIVE if installed else CapabilityState.BROKEN
        return CapabilityState.DORMANT if installed else CapabilityState.MISSING

    def toggle(self, cap: Capability, cfg: Config, *, enabled: bool) -> Config:
        """A copy of `cfg` with this capability's switch set.

        Deep-copied so the caller's object is never mutated in place: a TUI
        that toggles and then cancels must be able to discard the result.

        Refuses a capability with no switch rather than returning the config
        unchanged, which would let a surface render a toggle that does nothing.
        """
        if not cap.config_path:
            raise ValueError(f"capability {cap.name!r} has no config switch to set")

        value: object = enabled
        if cap.cardinality is Cardinality.ONE:
            # The field holds a name, not a flag: writing `True` into
            # `agent.type` produces a config the loader rejects. And there is
            # no "off" for an exclusive choice — deselecting would leave the
            # field naming nothing, and the registry cannot invent which
            # sibling takes over.
            if not enabled:
                raise ValueError(
                    f"capability {cap.name!r} is an exclusive choice; select a sibling "
                    "instead of deselecting this one"
                )
            value = cap.name

        updated = copy.deepcopy(cfg)
        parts = cap.config_path.split(".")
        target: object = updated
        for part in parts[:-1]:
            target = getattr(target, part)
        setattr(target, parts[-1], value)
        return updated
