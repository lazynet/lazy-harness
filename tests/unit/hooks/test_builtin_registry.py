"""The builtin registry mirrors the builtins directory, entry for entry.

`BuiltinHookSpec.migrated` decides which execution path a builtin takes, so a
module the registry does not carry is a hook with no declared path rather than
a hook with a safe default: neither entry point would ever reach it. The list
is static and the directory is not, so completeness is asserted against the
glob rather than maintained by hand.
"""

from __future__ import annotations

from pathlib import Path

from lazy_harness.hooks.loader import _BUILTIN_HOOKS

_BUILTINS_DIR = Path(__file__).resolve().parents[3] / "src" / "lazy_harness" / "hooks" / "builtins"

#: Not hooks: the package marker and the helpers every hook imports.
_NOT_HOOKS = {"__init__", "_shared"}


def _modules_on_disk() -> set[str]:
    return {p.stem for p in _BUILTINS_DIR.glob("*.py") if p.stem not in _NOT_HOOKS}


def _modules_in_registry() -> set[str]:
    return {spec.module.rsplit(".", 1)[-1] for spec in _BUILTIN_HOOKS.values()}


def test_every_builtin_module_on_disk_is_registered() -> None:
    unregistered = sorted(_modules_on_disk() - _modules_in_registry())
    assert unregistered == [], f"builtins with no registry entry: {unregistered}"


def test_no_registry_entry_names_a_module_that_is_not_there() -> None:
    dangling = sorted(_modules_in_registry() - _modules_on_disk())
    assert dangling == [], f"registry entries with no module: {dangling}"


def test_each_registered_name_maps_to_a_module_of_its_own() -> None:
    """One name, one module: a shared module would give two hooks one marker."""
    assert len(_modules_in_registry()) == len(_BUILTIN_HOOKS)


def test_no_builtin_is_migrated_yet() -> None:
    """The runner is wired in this step; the three hooks migrate in the next.

    Flipping `migrated` without migrating the module sends a `main()` that
    takes no arguments an event object, so this asserts the transitional state
    rather than merely reading the field.
    """
    migrated = sorted(name for name, spec in _BUILTIN_HOOKS.items() if spec.migrated)
    assert migrated == [], f"migrated before their main() changed signature: {migrated}"
