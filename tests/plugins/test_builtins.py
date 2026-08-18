"""Tests for the builtin capability table."""

from __future__ import annotations


def test_the_three_tools_are_registered_as_capabilities() -> None:
    from lazy_harness.plugins.builtins import builtin_registry

    names = {c.name for c in builtin_registry().capabilities(kind="tool")}
    assert names == {"qmd", "engram", "graphify"}


def test_every_tool_capability_declares_a_binary() -> None:
    """A tool is defined by an external binary; without one there is nothing
    to probe and it belongs to some other kind."""
    from lazy_harness.plugins.builtins import builtin_registry

    for cap in builtin_registry().capabilities(kind="tool"):
        assert cap.binary, f"{cap.name} has no binary to probe"


def test_qmd_declares_no_config_switch() -> None:
    """`knowledge.search` carries only `engine`. Pointing qmd's switch at it —
    as the plan first proposed — makes `bool("qmd")` the enabled test, so an
    uninstalled qmd reports BROKEN where `lh doctor` has always said missing.
    """
    from lazy_harness.plugins.builtins import builtin_registry

    assert builtin_registry().get("qmd").config_path == ""


def test_pinned_versions_come_from_their_modules_not_a_copy() -> None:
    """Two homes for a pin is how they stop agreeing."""
    from lazy_harness.knowledge import graphify
    from lazy_harness.memory import engram
    from lazy_harness.plugins.builtins import builtin_registry

    reg = builtin_registry()
    assert reg.get("engram").pinned_version == engram.PINNED_VERSION
    assert reg.get("graphify").pinned_version == graphify.PINNED_VERSION


def test_every_declared_config_path_resolves_against_a_default_config() -> None:
    """A capability naming a key that is not in Config is a registration typo
    that nothing else would catch."""
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.builtins import builtin_registry
    from lazy_harness.plugins.capabilities import _resolve

    cfg = Config()
    for cap in builtin_registry().capabilities():
        if cap.config_path:
            _resolve(cfg, cap.config_path, owner=cap.name)


def test_the_registry_is_the_same_object_across_calls() -> None:
    """Registration raises on a duplicate name, so rebuilding the table per
    call would make the second call explode."""
    from lazy_harness.plugins.builtins import builtin_registry

    assert builtin_registry() is builtin_registry()


def test_every_default_on_hook_is_registered_with_its_event() -> None:
    """`DEFAULT_HOOKS` becomes derived data, so the table is what decides which
    hooks ship on. A hook registered but forgotten in the defaults is how one
    stops running with nothing reporting it."""
    from lazy_harness.plugins.builtins import builtin_registry

    hooks = builtin_registry().capabilities(kind="hook")
    on_by_default = {c.name: c.config_path for c in hooks if c.enabled_by_default}

    assert on_by_default["context-inject"] == "hooks.session_start.scripts"
    assert on_by_default["engram-persist"] == "hooks.session_stop.scripts"
    assert len(on_by_default) == 12


def test_the_three_any_event_hooks_are_knowingly_absent() -> None:
    """`herdr-context-gauge`, `post-tool-use-ansible-lint` and
    `user-prompt-goal` appear in no `DEFAULT_HOOKS` list, so no event is
    declared for them anywhere in the code — they attach wherever the user puts
    them. Giving them a fixed `config_path` would invent that event and answer
    wrongly for anyone who configured them elsewhere, so they are left out
    until the registry can express "enabled under any event"."""
    from lazy_harness.hooks.loader import list_builtin_hooks
    from lazy_harness.plugins.builtins import builtin_registry

    registered = {c.name for c in builtin_registry().capabilities(kind="hook")}
    missing = set(list_builtin_hooks()) - registered

    assert missing == {
        "herdr-context-gauge",
        "post-tool-use-ansible-lint",
        "user-prompt-goal",
    }


def test_default_hooks_is_derived_from_the_registry() -> None:
    from lazy_harness.deploy.defaults import DEFAULT_HOOKS
    from lazy_harness.plugins.builtins import builtin_registry

    from_registry: dict[str, list[str]] = {}
    for cap in builtin_registry().capabilities(kind="hook"):
        if not cap.enabled_by_default:
            continue
        event = cap.config_path.split(".")[1]
        from_registry.setdefault(event, []).append(cap.name)

    assert {k: sorted(v) for k, v in DEFAULT_HOOKS.items()} == {
        k: sorted(v) for k, v in from_registry.items()
    }
