import tomllib
from pathlib import Path


def test_context_inject_yaml_parser_is_a_runtime_dependency() -> None:
    project = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())

    assert "pyyaml>=6.0" in project["project"]["dependencies"]
