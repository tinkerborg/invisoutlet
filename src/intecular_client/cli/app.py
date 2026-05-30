"""The Typer application and global options.

This module defines the ``app`` referenced by the ``intecular`` console entry
point. Commands live in :mod:`intecular_client.cli.commands` and are attached
here via each module's ``register`` function.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import typer

from .commands import register_all
from .state import CLIState

app = typer.Typer(
    name="intecular",
    help="Command-line tool for Intecular smart outlets.",
    rich_markup_mode="rich",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    """Print the package version and exit when ``--version`` is passed."""
    if not value:
        return
    try:
        typer.echo(version("intecular-client"))
    except PackageNotFoundError:
        typer.echo("unknown")
    raise typer.Exit


@app.callback()
def main(
    ctx: typer.Context,
    host: str | None = typer.Option(
        None, "--host", help="Device IP address (overrides the saved default)."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation for destructive commands."
    ),
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Store global options for the invoked command."""
    ctx.obj = CLIState(host=host, yes=yes)


register_all(app)

# Click command object, exposed for docs generation (mkdocs-click).
cli = typer.main.get_command(app)
