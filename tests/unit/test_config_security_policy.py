"""Security policy persistence must preserve the meaning of omitted scripts."""

from __future__ import annotations

import tomllib

import pytest

from lazy_harness.agents.registry import get_agent
from lazy_harness.core.config import ConfigError, load_config, save_config
from lazy_harness.deploy.defaults import merge_with_defaults


@pytest.mark.parametrize("destination", ["new", "existing", "different-scripts"])
@pytest.mark.parametrize("scripts", [None, [], ["pre-tool-use-security"]])
def test_security_policy_round_trip_preserves_options_and_script_presence(
    tmp_path, destination, scripts
):
    source = tmp_path / "source.toml"
    source.write_text(
        '[harness]\nversion = "1"\n[hooks.pre_tool_use]\n'
        'recursive_delete_roots = ["/tmp/cleanup"]\ndenied_commands = ["example-cli"]\n'
        'allow_patterns = ["legacy-pattern"]\nexternal = ["audit-command"]\n'
        + (f"scripts = {scripts!r}\n" if scripts is not None else "")
    )
    cfg = load_config(source)
    dest = tmp_path / "destination.toml"
    if destination != "new":
        dest.write_text(
            '# preserved\n[harness]\nversion = "1"\n[hooks.pre_tool_use]\n'
            + ('scripts = ["different"]\n' if destination == "different-scripts" else "")
        )
    for _ in range(2):
        save_config(cfg, dest)
        raw = tomllib.loads(dest.read_text())["hooks"]["pre_tool_use"]
        assert raw["recursive_delete_roots"] == ["/tmp/cleanup"]
        assert raw["denied_commands"] == ["example-cli"]
        assert raw["allow_patterns"] == ["legacy-pattern"]
        assert raw["external"] == ["audit-command"]
        assert ("scripts" in raw) == (scripts is not None)
        cfg = load_config(dest)
        policy = cfg.hooks["pre_tool_use"]
        assert policy.recursive_delete_roots == ["/tmp/cleanup"]
        assert policy.denied_commands == ["example-cli"]
        effective = merge_with_defaults(cfg.hooks, get_agent("claude-code"))["pre_tool_use"]
        if scripts is None:
            assert "pre-tool-use-security" in effective
            assert effective == merge_with_defaults({}, get_agent("claude-code"))["pre_tool_use"]
        else:
            assert effective == scripts
    policy.recursive_delete_roots = []
    policy.denied_commands = []
    save_config(cfg, dest)
    reread = load_config(dest).hooks["pre_tool_use"]
    assert reread.recursive_delete_roots == [] and reread.denied_commands == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("recursive_delete_roots", '"/tmp"'),
        ("recursive_delete_roots", "[7]"),
        ("recursive_delete_roots", '[""]'),
        ("recursive_delete_roots", '["relative"]'),
        ("recursive_delete_roots", '["/"]'),
        ("recursive_delete_roots", '["/../"]'),
        ("denied_commands", "false"),
        ("denied_commands", "[7]"),
        ("denied_commands", '[""]'),
        ("denied_commands", '["/bin/example"]'),
        ("denied_commands", '["example.*"]'),
        ("denied_commands", '["example tool"]'),
        ("denied_comands", '["example"]'),
    ],
)
def test_invalid_policy_names_the_key(tmp_path, key, value):
    path = tmp_path / "config.toml"
    path.write_text(f'[harness]\nversion = "1"\n[hooks.pre_tool_use]\n{key} = {value}\n')
    with pytest.raises(ConfigError, match=key):
        load_config(path)


def test_cleanup_root_symlink_to_filesystem_root_is_invalid(tmp_path):
    link = tmp_path / "root-link"
    link.symlink_to("/", target_is_directory=True)
    path = tmp_path / "config.toml"
    path.write_text(
        f'[harness]\nversion = "1"\n[hooks.pre_tool_use]\nrecursive_delete_roots = ["{link}"]\n'
    )
    with pytest.raises(ConfigError, match="recursive_delete_roots"):
        load_config(path)


def test_policy_on_another_event_is_rejected(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[harness]\nversion = "1"\n[hooks.session_start]\ndenied_commands = ["example"]\n'
    )
    with pytest.raises(ConfigError, match="denied_commands.*pre_tool_use"):
        load_config(path)


@pytest.mark.parametrize("existing", [False, True])
def test_memory_thresholds_survive_with_security_policy(tmp_path, existing):
    from lazy_harness.hooks.builtins.pre_tool_use_memory_size import load_claude_md_thresholds

    source = tmp_path / "source.toml"
    source.write_text(
        '[harness]\nversion = "1"\n[hooks.pre_tool_use]\n'
        "claude_md_max_lines = 73\nclaude_md_max_bytes = 4321\n"
        'denied_commands = ["example"]\n'
    )
    cfg = load_config(source)
    target = tmp_path / "target.toml"
    if existing:
        target.write_text(source.read_text())
    for _ in range(2):
        save_config(cfg, target)
        cfg = load_config(target)
        assert cfg.hooks["pre_tool_use"].claude_md_max_lines == 73
        assert cfg.hooks["pre_tool_use"].claude_md_max_bytes == 4321
        assert load_claude_md_thresholds(target) == (73, 4321)
        assert "scripts" not in tomllib.loads(target.read_text())["hooks"]["pre_tool_use"]
    cfg.hooks["pre_tool_use"].claude_md_max_lines = None
    cfg.hooks["pre_tool_use"].claude_md_max_bytes = None
    save_config(cfg, target)
    assert load_claude_md_thresholds(target) == load_claude_md_thresholds(tmp_path / "missing")


@pytest.mark.parametrize("key", ["claude_md_max_lines", "claude_md_max_bytes"])
@pytest.mark.parametrize("value", ["true", "false", "0", "-1", "1.5", '"7"', "[]"])
def test_memory_thresholds_require_positive_integers(tmp_path, key, value):
    from lazy_harness.hooks.builtins.pre_tool_use_memory_size import load_claude_md_thresholds

    path = tmp_path / "config.toml"
    path.write_text(f'[harness]\nversion = "1"\n[hooks.pre_tool_use]\n{key} = {value}\n')
    with pytest.raises(ConfigError, match=key) as exc:
        load_config(path)
    assert "positive integer" in str(exc.value)
    assert load_claude_md_thresholds(path) == load_claude_md_thresholds(tmp_path / "missing")


def test_saving_policy_preserves_unchanged_script_comments(tmp_path):
    path = tmp_path / "config.toml"
    script_block = 'scripts = [\n  "pre-tool-use-security", # retained\n]\n'
    path.write_text('[harness]\nversion = "1"\n[hooks.pre_tool_use]\n' + script_block)
    cfg = load_config(path)
    save_config(cfg, path)
    assert script_block in path.read_text()


@pytest.mark.parametrize("root", ["/", "//", "/./", "/../"])
def test_public_policy_validator_rejects_root_aliases(root):
    from lazy_harness.core.config import parse_security_policy

    with pytest.raises(ConfigError, match="recursive_delete_roots"):
        parse_security_policy({"recursive_delete_roots": [root]})


@pytest.mark.parametrize("raw", [None, 7, []])
def test_public_policy_validator_rejects_non_tables(raw):
    from lazy_harness.core.config import parse_security_policy

    with pytest.raises(ConfigError, match="hooks.pre_tool_use"):
        parse_security_policy(raw)


def test_public_policy_validator_returns_only_security_fields():
    from lazy_harness.core.config import parse_security_policy

    assert parse_security_policy(
        {
            "denied_commands": ["example-cli"],
            "recursive_delete_roots": ["/tmp/cleanup"],
            "claude_md_max_lines": 73,
            "claude_md_max_bytes": 4321,
            "scripts": [],
            "external": [],
            "allow_patterns": [],
        }
    ) == {"denied_commands": ["example-cli"], "recursive_delete_roots": ["/tmp/cleanup"]}
    assert parse_security_policy({"claude_md_max_lines": False}) == {
        "denied_commands": [],
        "recursive_delete_roots": [],
    }
