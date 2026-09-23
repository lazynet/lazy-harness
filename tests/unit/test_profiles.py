"""Tests for profile management."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.config import Config, HarnessConfig, ProfileEntry, ProfilesConfig


def _make_config(
    tmp_path: Path, profiles: dict[str, ProfileEntry] | None = None
) -> tuple[Config, Path]:
    """Helper to create a Config with profiles pointing to tmp dirs."""
    items = profiles or {
        "personal": ProfileEntry(
            config_dir=str(tmp_path / ".claude-personal"),
            roots=["~"],
        ),
    }
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(default="personal", items=items),
    )
    return cfg, tmp_path


def test_list_profiles(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import list_profiles

    cfg, _ = _make_config(tmp_path)
    result = list_profiles(cfg)
    assert len(result) == 1
    assert result[0].name == "personal"
    assert result[0].is_default is True


def test_list_profiles_multiple(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import list_profiles

    cfg, _ = _make_config(
        tmp_path,
        {
            "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-personal"), roots=["~"]),
            "work": ProfileEntry(config_dir=str(tmp_path / ".claude-work"), roots=["~/work"]),
        },
    )
    cfg.profiles.default = "personal"
    result = list_profiles(cfg)
    assert len(result) == 2
    names = {p.name for p in result}
    assert names == {"personal", "work"}


def test_add_profile(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import add_profile

    cfg, _ = _make_config(tmp_path)
    add_profile(cfg, "work", str(tmp_path / ".claude-work"), ["~/work"])
    assert "work" in cfg.profiles.items
    assert cfg.profiles.items["work"].config_dir == str(tmp_path / ".claude-work")


def test_add_profile_duplicate(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import ProfileError, add_profile

    cfg, _ = _make_config(tmp_path)
    with pytest.raises(ProfileError, match="already exists"):
        add_profile(cfg, "personal", str(tmp_path / ".claude-personal"), ["~"])


def test_remove_profile(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import remove_profile

    cfg, _ = _make_config(
        tmp_path,
        {
            "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-personal"), roots=["~"]),
            "work": ProfileEntry(config_dir=str(tmp_path / ".claude-work"), roots=["~/work"]),
        },
    )
    remove_profile(cfg, "work")
    assert "work" not in cfg.profiles.items


def test_remove_default_profile_fails(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import ProfileError, remove_profile

    cfg, _ = _make_config(tmp_path)
    with pytest.raises(ProfileError, match="default"):
        remove_profile(cfg, "personal")


def test_remove_nonexistent_profile(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import ProfileError, remove_profile

    cfg, _ = _make_config(tmp_path)
    with pytest.raises(ProfileError, match="not found"):
        remove_profile(cfg, "ghost")


def test_resolve_profile_by_cwd(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import resolve_profile

    work_root = tmp_path / "work" / "project"
    work_root.mkdir(parents=True)
    cfg, _ = _make_config(
        tmp_path,
        {
            "personal": ProfileEntry(
                config_dir=str(tmp_path / ".claude-personal"), roots=[str(tmp_path)]
            ),
            "work": ProfileEntry(
                config_dir=str(tmp_path / ".claude-work"),
                roots=[str(tmp_path / "work")],
            ),
        },
    )
    result = resolve_profile(cfg, cwd=work_root)
    assert result == "work"


def test_resolve_profile_falls_back_to_default(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import resolve_profile

    cfg, _ = _make_config(tmp_path)
    result = resolve_profile(cfg, cwd=Path("/some/random/path"))
    assert result == "personal"


def test_resolve_with_source_reports_a_root_match(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import resolve_profile_with_source

    work_root = tmp_path / "work" / "project"
    work_root.mkdir(parents=True)
    cfg, _ = _make_config(
        tmp_path,
        {
            "personal": ProfileEntry(
                config_dir=str(tmp_path / ".claude-personal"), roots=[str(tmp_path)]
            ),
            "work": ProfileEntry(
                config_dir=str(tmp_path / ".claude-work"), roots=[str(tmp_path / "work")]
            ),
        },
    )

    resolution = resolve_profile_with_source(cfg, cwd=work_root)

    assert resolution.name == "work"
    assert resolution.source == "root-match"


def test_resolve_with_source_marks_the_silent_fallback(tmp_path: Path) -> None:
    """The dangerous case: no root matched, so the default profile is a guess."""
    from lazy_harness.core.profiles import resolve_profile_with_source

    cfg, _ = _make_config(tmp_path)

    resolution = resolve_profile_with_source(cfg, cwd=Path("/some/random/path"))

    assert resolution.name == "personal"
    assert resolution.source == "default-fallback"


def test_resolve_with_source_marks_an_override_as_explicit(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import resolve_profile_with_source

    cfg, _ = _make_config(tmp_path)

    resolution = resolve_profile_with_source(
        cfg, cwd=Path("/some/random/path"), override="personal"
    )

    assert resolution.name == "personal"
    assert resolution.source == "explicit"


def test_resolve_with_source_rejects_an_unknown_override(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import ProfileError, resolve_profile_with_source

    cfg, _ = _make_config(tmp_path)

    with pytest.raises(ProfileError, match="ghost"):
        resolve_profile_with_source(cfg, cwd=tmp_path, override="ghost")


@pytest.mark.parametrize("cwd", [Path("/some/random/path"), None])
def test_resolve_profile_agrees_with_resolve_with_source(tmp_path: Path, cwd: Path | None) -> None:
    """Two code paths answering the same question must not diverge."""
    from lazy_harness.core.profiles import resolve_profile, resolve_profile_with_source

    cfg, _ = _make_config(tmp_path)

    assert resolve_profile(cfg, cwd) == resolve_profile_with_source(cfg, cwd).name


# --- D7: two profiles sharing a root, unresolved without a default ----------


def test_resolve_refuses_a_shared_root_with_no_default(tmp_path: Path) -> None:
    """Design decision 7: the tie is refused, not silently broken by TOML order."""
    from lazy_harness.core.profiles import ProfileError, resolve_profile_with_source

    shared = tmp_path / "shared"
    shared.mkdir()
    cfg, _ = _make_config(
        tmp_path,
        {
            "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-x"), roots=[str(shared)]),
            "experiment": ProfileEntry(
                config_dir=str(tmp_path / ".other-x"), roots=[str(shared)], agent="other"
            ),
        },
    )

    with pytest.raises(ProfileError, match="personal") as excinfo:
        resolve_profile_with_source(cfg, cwd=shared)
    assert "experiment" in str(excinfo.value)


def test_resolve_picks_the_root_default_among_a_shared_root(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import resolve_profile_with_source

    shared = tmp_path / "shared"
    shared.mkdir()
    cfg, _ = _make_config(
        tmp_path,
        {
            "personal": ProfileEntry(
                config_dir=str(tmp_path / ".claude-x"), roots=[str(shared)], root_default=True
            ),
            "experiment": ProfileEntry(
                config_dir=str(tmp_path / ".other-x"), roots=[str(shared)], agent="other"
            ),
        },
    )

    resolution = resolve_profile_with_source(cfg, cwd=shared)

    assert resolution.name == "personal"
    assert resolution.source == "root-match"


def test_resolve_is_unaffected_when_only_one_profile_claims_the_root(tmp_path: Path) -> None:
    """No ambiguity, no refusal: the common case must stay exactly as it was."""
    from lazy_harness.core.profiles import resolve_profile_with_source

    work_root = tmp_path / "work"
    work_root.mkdir()
    cfg, _ = _make_config(
        tmp_path,
        {
            "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-x"), roots=[str(tmp_path)]),
            "work": ProfileEntry(config_dir=str(tmp_path / ".claude-w"), roots=[str(work_root)]),
        },
    )

    resolution = resolve_profile_with_source(cfg, cwd=work_root)

    assert resolution.name == "work"
    assert resolution.source == "root-match"


def test_collect_shared_roots_is_empty_when_no_root_is_shared(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import collect_shared_roots

    cfg, _ = _make_config(
        tmp_path,
        {
            "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-x"), roots=[str(tmp_path)]),
            "work": ProfileEntry(
                config_dir=str(tmp_path / ".claude-w"), roots=[str(tmp_path / "work")]
            ),
        },
    )

    assert collect_shared_roots(cfg) == []


def test_collect_shared_roots_names_every_claimant_and_its_agent(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import collect_shared_roots

    shared = tmp_path / "shared"
    cfg, _ = _make_config(
        tmp_path,
        {
            "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-x"), roots=[str(shared)]),
            "experiment": ProfileEntry(
                config_dir=str(tmp_path / ".other-x"), roots=[str(shared)], agent="null"
            ),
        },
    )

    result = collect_shared_roots(cfg)

    assert len(result) == 1
    assert result[0].root == str(shared)
    assert set(result[0].profiles) == {"personal", "experiment"}
    assert result[0].agents == {"personal": "claude-code", "experiment": "null"}
    assert result[0].default is None


def test_collect_shared_roots_reports_the_declared_default(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import collect_shared_roots

    shared = tmp_path / "shared"
    cfg, _ = _make_config(
        tmp_path,
        {
            "personal": ProfileEntry(
                config_dir=str(tmp_path / ".claude-x"), roots=[str(shared)], root_default=True
            ),
            "experiment": ProfileEntry(
                config_dir=str(tmp_path / ".other-x"), roots=[str(shared)], agent="null"
            ),
        },
    )

    result = collect_shared_roots(cfg)

    assert result[0].default == "personal"


def test_an_explicit_override_short_circuits_the_shared_root_refusal(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import resolve_profile_with_source

    shared = tmp_path / "shared"
    shared.mkdir()
    cfg, _ = _make_config(
        tmp_path,
        {
            "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-x"), roots=[str(shared)]),
            "experiment": ProfileEntry(
                config_dir=str(tmp_path / ".other-x"), roots=[str(shared)], agent="other"
            ),
        },
    )

    resolution = resolve_profile_with_source(cfg, cwd=shared, override="experiment")

    assert resolution.name == "experiment"
    assert resolution.source == "explicit"


# --- --agent filtering (Task 4) --------------------------------------------- #


def test_agent_filter_on_a_shared_root_picks_that_agents_root_default(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import resolve_profile_with_source

    shared = tmp_path / "shared"
    shared.mkdir()
    cfg, _ = _make_config(
        tmp_path,
        {
            "claude-x": ProfileEntry(
                config_dir=str(tmp_path / ".claude-x"), roots=[str(shared)], root_default=True
            ),
            "codex-x": ProfileEntry(
                config_dir=str(tmp_path / ".codex-x"), roots=[str(shared)], agent="codex"
            ),
        },
    )

    assert resolve_profile_with_source(cfg, cwd=shared).name == "claude-x"
    assert resolve_profile_with_source(cfg, cwd=shared, agent="codex").name == "codex-x"


def test_agent_filter_with_no_root_match_never_falls_back_to_another_agents_default(
    tmp_path: Path,
) -> None:
    """The default profile runs Claude Code; `--agent codex` must never launch it."""
    from lazy_harness.core.profiles import resolve_profile_with_source

    outside = tmp_path / "outside"
    outside.mkdir()
    cfg, _ = _make_config(
        tmp_path,
        {
            "claude-x": ProfileEntry(config_dir=str(tmp_path / ".claude-x"), roots=["~"]),
            "codex-x": ProfileEntry(config_dir=str(tmp_path / ".codex-x"), agent="codex"),
        },
    )
    cfg.profiles.default = "claude-x"

    resolution = resolve_profile_with_source(cfg, cwd=outside, agent="codex")

    assert resolution.name == "codex-x"
    assert resolution.source == "default-fallback"


def test_agent_filter_with_two_candidates_and_no_root_match_refuses(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import ProfileError, resolve_profile_with_source

    outside = tmp_path / "outside"
    outside.mkdir()
    cfg, _ = _make_config(
        tmp_path,
        {
            "claude-x": ProfileEntry(config_dir=str(tmp_path / ".claude-x"), roots=["~"]),
            "codex-x": ProfileEntry(config_dir=str(tmp_path / ".codex-x"), agent="codex"),
            "codex-y": ProfileEntry(config_dir=str(tmp_path / ".codex-y"), agent="codex"),
        },
    )
    cfg.profiles.default = "claude-x"

    with pytest.raises(ProfileError, match="codex"):
        resolve_profile_with_source(cfg, cwd=outside, agent="codex")


def test_override_and_agent_agreeing_resolves_explicit(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import resolve_profile_with_source

    cfg, _ = _make_config(
        tmp_path,
        {"codex-x": ProfileEntry(config_dir=str(tmp_path / ".codex-x"), agent="codex")},
    )

    resolution = resolve_profile_with_source(cfg, override="codex-x", agent="codex")

    assert resolution.name == "codex-x"
    assert resolution.source == "explicit"


def test_override_and_agent_disagreeing_is_refused(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import ProfileError, resolve_profile_with_source

    cfg, _ = _make_config(
        tmp_path,
        {"claude-x": ProfileEntry(config_dir=str(tmp_path / ".claude-x"))},
    )

    with pytest.raises(ProfileError, match="claude-x"):
        resolve_profile_with_source(cfg, override="claude-x", agent="codex")


def test_unknown_agent_prefix_is_refused(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import ProfileError, resolve_profile_with_source

    cfg, _ = _make_config(tmp_path)

    with pytest.raises(ProfileError, match="nope"):
        resolve_profile_with_source(cfg, agent="nope")


def test_agent_filter_is_a_no_op_smoke_test(tmp_path: Path) -> None:
    """The parameter-less call must resolve exactly as it always has."""
    from lazy_harness.core.profiles import resolve_profile_with_source

    cfg, _ = _make_config(tmp_path)

    assert resolve_profile_with_source(cfg).name == "personal"


def test_agent_filter_skips_a_profile_whose_agent_has_no_prefix(tmp_path: Path) -> None:
    """A profile with a typo'd or deregistered agent cannot match any `--agent`,
    so it must not blow up the candidate filter for everyone else."""
    from lazy_harness.core.profiles import resolve_profile_with_source

    cfg, _ = _make_config(
        tmp_path,
        {
            "claude-x": ProfileEntry(config_dir=str(tmp_path / ".claude-x"), roots=["~"]),
            "broken": ProfileEntry(config_dir=str(tmp_path / ".broken"), agent="claud"),
        },
    )
    cfg.profiles.default = "claude-x"

    resolution = resolve_profile_with_source(cfg, agent="claude")

    assert resolution.name == "claude-x"
