"""Top-level CLI entrypoint for lazy-harness."""

from __future__ import annotations

import click

from lazy_harness import __version__


@click.group()
@click.version_option(__version__, prog_name="lazy-harness")
def cli() -> None:
    """lazy-harness — A cross-platform harnessing framework for AI coding agents."""


def register_commands() -> None:
    """Register all subcommands. Called after imports to avoid circular deps."""
    from lazy_harness.cli.init_cmd import init_cmd
    from lazy_harness.cli.profile_cmd import profile
    from lazy_harness.cli.doctor_cmd import doctor
    from lazy_harness.cli.deploy_cmd import deploy

    cli.add_command(init_cmd, "init")
    cli.add_command(profile, "profile")
    cli.add_command(doctor, "doctor")
    cli.add_command(deploy, "deploy")


register_commands()
