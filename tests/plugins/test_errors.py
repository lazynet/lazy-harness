"""Tests for plugins.errors."""

from __future__ import annotations

import pytest

from lazy_harness.plugins.errors import (
    PluginConflict,
    PluginContractError,
    PluginError,
    PluginNotFound,
)


def test_plugin_error_is_base() -> None:
    assert issubclass(PluginNotFound, PluginError)
    assert issubclass(PluginConflict, PluginError)
    assert issubclass(PluginContractError, PluginError)


def test_plugin_not_found_carries_name_and_kind() -> None:
    err = PluginNotFound(kind="metrics_sink", name="http_remote")
    assert "metrics_sink" in str(err)
    assert "http_remote" in str(err)


def test_plugin_conflict_mentions_both_registrations() -> None:
    err = PluginConflict(kind="metrics_sink", name="http_remote", origins=["builtin", "ext:acme"])
    msg = str(err)
    assert "builtin" in msg
    assert "ext:acme" in msg


def test_plugin_error_is_exception() -> None:
    with pytest.raises(PluginError):
        raise PluginNotFound(kind="x", name="y")
