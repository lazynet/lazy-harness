"""Feature status helper for lh doctor (per ADR-018, ADR-025).

The three probe functions this file used to carry — one each for qmd, engram
and graphify — implemented the same four-state model three times. They are now
one pass over the `tool` capabilities in the registry, so a tool added to that
table shows up here without editing this file.

`FeatureStatus` is kept as the return type: `cli/doctor_cmd.py` renders it, and
this migration changes no output.
"""

from __future__ import annotations

from dataclasses import dataclass

from lazy_harness.core.config import Config
from lazy_harness.core.versions import parse_version
from lazy_harness.plugins.builtins import builtin_registry
from lazy_harness.plugins.capabilities import (
    Capability,
    CapabilityState,
    Probe,
    _resolve,
    which_probe,
)

# The registry's vocabulary is wider than doctor's, because a capability with
# no external binary has ON/OFF states that no tool can be in. Only the four
# states a tool can reach are mapped.
_STATE_NAMES = {
    CapabilityState.ACTIVE: "active",
    CapabilityState.DORMANT: "dormant",
    CapabilityState.BROKEN: "broken",
    CapabilityState.MISSING: "missing",
}


@dataclass
class FeatureStatus:
    name: str
    section: str
    state: str  # one of: active, dormant, missing, broken
    installed_version: str
    pinned_version: str
    install_hint: str
    enable_hint: str


def _probe_version(binary: str) -> str:
    """Run `<binary> --version` and return the version it prints, or "" on failure."""
    import subprocess

    try:
        result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return parse_version(result.stdout)


def _section_of(cap: Capability) -> str:
    """The config section doctor names for this capability.

    A capability's `config_path` ends in the key; the section is everything
    before it. qmd has no path at all, so its section is spelled out — the
    label doctor has always printed is `knowledge.search`, and dropping it
    would change the output this migration promises to preserve.
    """
    if not cap.config_path:
        return "knowledge.search" if cap.name == "qmd" else ""
    return cap.config_path.rsplit(".", 1)[0]


def _pin_for(cap: Capability, cfg: Config) -> str:
    """The pin doctor reports, read from config first.

    ADR-022 and ADR-023 both say the config's `version` key is the single
    source of truth for the pin. The module constant was being reported
    instead, so `lh doctor` contradicted the config the user had just edited
    and the field promised a behaviour it did not have.

    A capability with no pin of its own — qmd — asks the config nothing: its
    section has no `version` key, and `_resolve` is deliberately strict about
    a path that does not exist.
    """
    if not cap.pinned_version:
        return ""
    declared = _resolve(cfg, f"{_section_of(cap)}.version", owner=cap.name)
    return declared if isinstance(declared, str) and declared else cap.pinned_version


def _status_for(cap: Capability, cfg: Config, *, probe: Probe) -> FeatureStatus:
    state = _STATE_NAMES[builtin_registry().state(cap, cfg, probe=probe)]
    installed = state in ("active", "dormant")
    detected = _probe_version(cap.binary) if installed else ""
    pin = _pin_for(cap, cfg)

    install_hint = ""
    if state in ("missing", "broken") and cap.install_hint:
        install_hint = cap.install_hint.format(pin=pin)

    enable_hint = ""
    if state == "dormant":
        section = _section_of(cap)
        enable_hint = f"Set [{section}].enabled = true to activate."

    return FeatureStatus(
        name=cap.name,
        section=_section_of(cap),
        state=state,
        installed_version=detected,
        pinned_version=pin,
        install_hint=install_hint,
        enable_hint=enable_hint,
    )


def collect_feature_statuses(cfg: Config, *, probe: Probe = which_probe) -> list[FeatureStatus]:
    """Collect status for every optional tool the harness knows about."""
    reg = builtin_registry()
    return [_status_for(cap, cfg, probe=probe) for cap in reg.capabilities(kind="tool")]
