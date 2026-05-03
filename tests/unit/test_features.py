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
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: True)
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "2.1.0")

    statuses = collect_feature_statuses(Config())
    qmd = next(s for s in statuses if s.name == "qmd")
    assert qmd.state == "active"
    assert qmd.installed_version == "2.1.0"


def test_qmd_status_missing_when_not_installed(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)

    statuses = collect_feature_statuses(Config())
    qmd = next(s for s in statuses if s.name == "qmd")
    assert qmd.state == "missing"
    assert qmd.installed_version == ""
    assert "qmd" in qmd.install_hint.lower()


def test_engram_status_active(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: True)
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "1.15.4")

    cfg = Config()
    cfg.memory.engram.enabled = True

    statuses = collect_feature_statuses(cfg)
    engram = next(s for s in statuses if s.name == "engram")
    assert engram.state == "active"
    assert engram.installed_version == "1.15.4"
    assert engram.pinned_version == "1.15.4"


def test_engram_status_dormant_when_installed_but_disabled(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: True)
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "1.15.4")

    cfg = Config()
    cfg.memory.engram.enabled = False

    statuses = collect_feature_statuses(cfg)
    engram = next(s for s in statuses if s.name == "engram")
    assert engram.state == "dormant"
    assert "[memory.engram].enabled" in engram.enable_hint


def test_engram_status_missing(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)

    cfg = Config()
    cfg.memory.engram.enabled = False

    statuses = collect_feature_statuses(cfg)
    engram = next(s for s in statuses if s.name == "engram")
    assert engram.state == "missing"
    assert "engram" in engram.install_hint.lower()


def test_engram_status_broken_when_enabled_but_missing(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)

    cfg = Config()
    cfg.memory.engram.enabled = True

    statuses = collect_feature_statuses(cfg)
    engram = next(s for s in statuses if s.name == "engram")
    assert engram.state == "broken"


def test_graphify_status_active(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: True)
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "0.6.9")

    cfg = Config()
    cfg.knowledge.structure.enabled = True

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "active"
    assert graphify.installed_version == "0.6.9"
    assert graphify.pinned_version == "0.6.9"


def test_graphify_status_dormant_when_installed_but_disabled(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: True)
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "0.6.9")

    cfg = Config()
    cfg.knowledge.structure.enabled = False

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "dormant"
    assert "[knowledge.structure].enabled" in graphify.enable_hint


def test_graphify_status_missing(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: False)

    cfg = Config()
    cfg.knowledge.structure.enabled = False

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "missing"
    assert "graphify" in graphify.install_hint.lower()


def test_graphify_status_broken_when_enabled_but_missing(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: False)

    cfg = Config()
    cfg.knowledge.structure.enabled = True

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "broken"
