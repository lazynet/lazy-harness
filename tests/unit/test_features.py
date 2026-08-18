"""Tests for the features helper used by lh doctor."""

from __future__ import annotations

from unittest.mock import patch  # noqa: F401


def test_feature_status_dataclass_shape() -> None:
    from lazy_harness.features import FeatureStatus

    s = FeatureStatus(
        name="qmd",
        section="knowledge.search",
        state="active",
        installed_version="2.1.0",
        pinned_version="",
        install_hint="",
        enable_hint="",
    )
    assert s.name == "qmd"
    assert s.state == "active"


def test_qmd_status_active_when_installed(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    installed = ['qmd']
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "2.1.0")

    statuses = collect_feature_statuses(Config())
    qmd = next(s for s in statuses if s.name == "qmd")
    assert qmd.state == "active"
    assert qmd.installed_version == "2.1.0"


def test_qmd_status_missing_when_not_installed(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    installed = []
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )

    statuses = collect_feature_statuses(Config())
    qmd = next(s for s in statuses if s.name == "qmd")
    assert qmd.state == "missing"
    assert qmd.installed_version == ""
    assert "qmd" in qmd.install_hint.lower()


def test_engram_status_active(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    installed = ['engram']
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "1.20.0")

    cfg = Config()
    cfg.memory.engram.enabled = True

    statuses = collect_feature_statuses(cfg)
    engram = next(s for s in statuses if s.name == "engram")
    assert engram.state == "active"
    assert engram.installed_version == "1.20.0"
    assert engram.pinned_version == "1.20.0"


def test_engram_status_dormant_when_installed_but_disabled(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    installed = ['engram']
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "1.20.0")

    cfg = Config()
    cfg.memory.engram.enabled = False

    statuses = collect_feature_statuses(cfg)
    engram = next(s for s in statuses if s.name == "engram")
    assert engram.state == "dormant"
    assert "[memory.engram].enabled" in engram.enable_hint


def test_engram_status_missing(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    installed = []
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )

    cfg = Config()
    cfg.memory.engram.enabled = False

    statuses = collect_feature_statuses(cfg)
    engram = next(s for s in statuses if s.name == "engram")
    assert engram.state == "missing"
    assert "engram" in engram.install_hint.lower()


def test_engram_status_broken_when_enabled_but_missing(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    installed = []
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )

    cfg = Config()
    cfg.memory.engram.enabled = True

    statuses = collect_feature_statuses(cfg)
    engram = next(s for s in statuses if s.name == "engram")
    assert engram.state == "broken"


def test_graphify_status_active(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    installed = ['graphify']
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "0.9.41")

    cfg = Config()
    cfg.knowledge.structure.enabled = True

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "active"
    assert graphify.installed_version == "0.9.41"
    assert graphify.pinned_version == "0.9.41"


def test_graphify_status_dormant_when_installed_but_disabled(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    installed = ['graphify']
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "0.9.41")

    cfg = Config()
    cfg.knowledge.structure.enabled = False

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "dormant"
    assert "[knowledge.structure].enabled" in graphify.enable_hint


def test_graphify_status_missing(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    installed = []
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )

    cfg = Config()
    cfg.knowledge.structure.enabled = False

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "missing"
    assert "graphify" in graphify.install_hint.lower()


def test_graphify_status_broken_when_enabled_but_missing(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    installed = []
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )

    cfg = Config()
    cfg.knowledge.structure.enabled = True

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "broken"


def test_collect_accepts_an_injected_probe(monkeypatch) -> None:
    """Paired with the tests above, which go through the default `shutil.which`.

    Both halves matter: injecting everywhere would leave `which_probe` untested,
    and patching `shutil.which` everywhere would leave the parameter untested.
    """
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "9.9.9")

    statuses = collect_feature_statuses(Config(), probe=lambda name: name == "graphify")

    by_name = {s.name: s for s in statuses}
    assert by_name["graphify"].state == "dormant"
    assert by_name["qmd"].state == "missing"
    assert by_name["engram"].state == "missing"


def test_engram_pinned_version_comes_from_config(monkeypatch) -> None:
    """ADR-022 makes config the single source of truth for the pin.

    Reporting the module constant instead means `lh doctor` contradicts the
    config the user just edited, and the config field promises a behaviour it
    does not have.
    """
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "9.9.9")

    cfg = Config()
    cfg.memory.engram.enabled = True
    cfg.memory.engram.version = "9.9.9"

    statuses = collect_feature_statuses(cfg)
    engram_status = next(s for s in statuses if s.name == "engram")
    assert engram_status.pinned_version == "9.9.9"


def test_graphify_pinned_version_comes_from_config(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "8.8.8")

    cfg = Config()
    cfg.knowledge.structure.enabled = True
    cfg.knowledge.structure.version = "8.8.8"

    statuses = collect_feature_statuses(cfg)
    graphify_status = next(s for s in statuses if s.name == "graphify")
    assert graphify_status.pinned_version == "8.8.8"


def test_install_hint_names_the_config_pin(monkeypatch) -> None:
    """The hint tells the user which version to install — from the config."""
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    monkeypatch.setattr("shutil.which", lambda name: None)

    cfg = Config()
    cfg.memory.engram.version = "9.9.9"

    statuses = collect_feature_statuses(cfg)
    engram_status = next(s for s in statuses if s.name == "engram")
    assert "9.9.9" in engram_status.install_hint


def test_probe_version_ignores_a_trailing_build_hash(monkeypatch) -> None:
    """qmd prints `qmd 2.5.3 (5b90e281d4)`.

    Taking the last token reported the hash as the installed version, and
    `lh doctor` rendered `v(5b90e281d4)` for months.
    """
    import subprocess
    from types import SimpleNamespace

    from lazy_harness.features import _probe_version

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="qmd 2.5.3 (5b90e281d4)\n"),
    )
    assert _probe_version("qmd") == "2.5.3"
