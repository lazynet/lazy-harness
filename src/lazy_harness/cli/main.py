"""Top-level CLI entrypoint for lazy-harness."""

from __future__ import annotations

import os
from collections.abc import Mapping

import click

from lazy_harness import __version__


def unusable_terminal_size_vars(environ: Mapping[str, str]) -> list[str]:
    """Size variables Rich would turn into a zero-wide console.

    Rich takes any all-digit `COLUMNS` or `LINES` as an explicit size, so the
    `COLUMNS=0` agent shells export skips its fallback and prints nothing.
    """
    return [
        name
        for name in ("COLUMNS", "LINES")
        if environ.get(name, "").isdigit() and int(environ[name]) == 0
    ]


@click.group()
@click.version_option(__version__, prog_name="lazy-harness")
def cli() -> None:
    """lazy-harness — A cross-platform harnessing framework for AI coding agents."""
    for name in unusable_terminal_size_vars(os.environ):
        del os.environ[name]


def register_commands() -> None:
    """Register all subcommands. Called after imports to avoid circular deps."""
    from lazy_harness.cli.deploy_cmd import deploy
    from lazy_harness.cli.doctor_cmd import doctor
    from lazy_harness.cli.hooks_cmd import hook_invoke, hooks
    from lazy_harness.cli.init_cmd import init as init_cmd
    from lazy_harness.cli.profile_cmd import profile
    from lazy_harness.cli.status_cmd import status

    cli.add_command(init_cmd, "init")
    cli.add_command(profile, "profile")
    cli.add_command(doctor, "doctor")
    cli.add_command(deploy, "deploy")
    cli.add_command(status, "status")
    cli.add_command(hooks, "hooks")
    cli.add_command(hook_invoke, "hook")

    from lazy_harness.cli.knowledge_cmd import knowledge

    cli.add_command(knowledge, "knowledge")

    from lazy_harness.cli.scheduler_cmd import scheduler

    cli.add_command(scheduler, "scheduler")

    from lazy_harness.cli.migrate_cmd import migrate

    cli.add_command(migrate, "migrate")

    from lazy_harness.cli.selftest_cmd import selftest

    cli.add_command(selftest, "selftest")

    from lazy_harness.cli.run_cmd import run

    cli.add_command(run, "run")

    from lazy_harness.cli.exec_cmd import exec_cmd

    cli.add_command(exec_cmd, "exec")

    from lazy_harness.cli.statusline_cmd import statusline

    cli.add_command(statusline, "statusline")

    from lazy_harness.cli.metrics_cmd import metrics

    cli.add_command(metrics, "metrics")

    from lazy_harness.cli.config_cmd import config

    cli.add_command(config, "config")

    from lazy_harness.cli.memory_cmd import memory

    cli.add_command(memory, "memory")

    from lazy_harness.cli.repo_cmd import repo

    cli.add_command(repo, "repo")


register_commands()
