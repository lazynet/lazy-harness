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
    from lazy_harness.cli.deploy_cmd import deploy
    from lazy_harness.cli.doctor_cmd import doctor
    from lazy_harness.cli.hooks_cmd import hooks
    from lazy_harness.cli.init_cmd import init as init_cmd
    from lazy_harness.cli.profile_cmd import profile
    from lazy_harness.cli.status_cmd import status

    cli.add_command(init_cmd, "init")
    cli.add_command(profile, "profile")
    cli.add_command(doctor, "doctor")
    cli.add_command(deploy, "deploy")
    cli.add_command(status, "status")
    cli.add_command(hooks, "hooks")

    from lazy_harness.cli.knowledge_cmd import knowledge

    cli.add_command(knowledge, "knowledge")

    from lazy_harness.cli.scheduler_cmd import scheduler

    cli.add_command(scheduler, "scheduler")

    from lazy_harness.cli.migrate_cmd import migrate

    cli.add_command(migrate, "migrate")


register_commands()
