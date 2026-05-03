"""Feature status helper for lh doctor (per ADR-018, ADR-025)."""

from __future__ import annotations

from dataclasses import dataclass

from lazy_harness.core.config import Config


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
    """Run `<binary> --version` and return the last token of stdout, or "" on failure."""
    import subprocess

    try:
        result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    parts = result.stdout.strip().split()
    return parts[-1] if parts else ""


def _qmd_status() -> FeatureStatus:
    from lazy_harness.knowledge import qmd

    if qmd.is_qmd_available():
        return FeatureStatus(
            name="qmd",
            section="knowledge.search",
            state="active",
            installed_version=_probe_version("qmd"),
            pinned_version="",
            install_hint="",
            enable_hint="",
        )
    return FeatureStatus(
        name="qmd",
        section="knowledge.search",
        state="missing",
        installed_version="",
        pinned_version="",
        install_hint="Install QMD to enable semantic search across the knowledge dir.",
        enable_hint="",
    )


def _engram_status(cfg: Config) -> FeatureStatus:
    from lazy_harness.memory import engram

    enabled = cfg.memory.engram.enabled
    installed = engram.is_engram_available()
    pinned = engram.PINNED_VERSION
    detected = _probe_version("engram") if installed else ""

    if enabled and installed:
        state = "active"
    elif installed and not enabled:
        state = "dormant"
    elif enabled and not installed:
        state = "broken"
    else:
        state = "missing"

    install_hint = (
        f"Install Engram (pin {pinned}) and set [memory.engram].enabled = true."
        if state in ("missing", "broken")
        else ""
    )
    enable_hint = "Set [memory.engram].enabled = true to activate." if state == "dormant" else ""

    return FeatureStatus(
        name="engram",
        section="memory.engram",
        state=state,
        installed_version=detected,
        pinned_version=pinned,
        install_hint=install_hint,
        enable_hint=enable_hint,
    )


def _graphify_status(cfg: Config) -> FeatureStatus:
    from lazy_harness.knowledge import graphify

    enabled = cfg.knowledge.structure.enabled
    installed = graphify.is_graphify_available()
    pinned = graphify.PINNED_VERSION
    detected = _probe_version("graphify") if installed else ""

    if enabled and installed:
        state = "active"
    elif installed and not enabled:
        state = "dormant"
    elif enabled and not installed:
        state = "broken"
    else:
        state = "missing"

    install_hint = (
        f"Install Graphify (pin {pinned}) and set [knowledge.structure].enabled = true."
        if state in ("missing", "broken")
        else ""
    )
    enable_hint = (
        "Set [knowledge.structure].enabled = true to activate." if state == "dormant" else ""
    )

    return FeatureStatus(
        name="graphify",
        section="knowledge.structure",
        state=state,
        installed_version=detected,
        pinned_version=pinned,
        install_hint=install_hint,
        enable_hint=enable_hint,
    )


def collect_feature_statuses(cfg: Config) -> list[FeatureStatus]:
    """Collect status for every optional tool the harness knows about."""
    return [_qmd_status(), _engram_status(cfg), _graphify_status(cfg)]
