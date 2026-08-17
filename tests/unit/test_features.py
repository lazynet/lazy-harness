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

    installed = ['engram']
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )
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
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "0.9.38")

    cfg = Config()
    cfg.knowledge.structure.enabled = True

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "active"
    assert graphify.installed_version == "0.9.38"
    assert graphify.pinned_version == "0.9.38"


def test_graphify_status_dormant_when_installed_but_disabled(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    installed = ['graphify']
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )
    monkeypatch.setattr("lazy_harness.features._probe_version", lambda binary: "0.9.38")

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
