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
from collections.abc import Callable
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


def _resolve(cfg: Config, dotted: str) -> object:
    """Walk a dotted path against the loaded `Config`.

    Raises rather than defaulting: a capability naming a key that does not
    exist is a registration bug, and answering `OFF` would hide it behind a
    plausible answer — which is how a config field can promise behaviour it
    never had.
    """
    current: object = cfg
    for part in dotted.split("."):
        current = getattr(current, part)
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

        enabled = bool(_resolve(cfg, cap.config_path))
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
        updated = copy.deepcopy(cfg)
        parts = cap.config_path.split(".")
        target: object = updated
        for part in parts[:-1]:
            target = getattr(target, part)
        setattr(target, parts[-1], enabled)
        return updated
