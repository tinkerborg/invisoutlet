"""The ``name`` group: list and set accessory names."""

from __future__ import annotations

import typer

from intecular_client import AccessoryName, IntecularClient

from .. import render
from ..state import run_with_client

name_app = typer.Typer(
    name="name", help="Manage accessory names.", no_args_is_help=True
)


def register(app: typer.Typer) -> None:
    """Attach the ``name`` group to ``app``."""
    app.add_typer(name_app)


@name_app.command("list")
def list_(ctx: typer.Context) -> None:
    """List the user-assigned accessory names."""
    run_with_client(ctx.obj, _list)


@name_app.command("set")
def set_(
    ctx: typer.Context,
    accessory: int = typer.Argument(..., help="Accessory index to rename."),
    name: str = typer.Argument(..., help="New accessory name."),
) -> None:
    """Rename a single accessory, preserving the others."""
    run_with_client(ctx.obj, lambda c: _set(c, accessory, name))


async def _list(client: IntecularClient) -> None:
    render.render_names(await client.get_accessory_names())


async def _set(client: IntecularClient, accessory: int, name: str) -> None:
    names = await client.get_accessory_names()
    if not any(entry.accessory == accessory for entry in names):
        names.append(AccessoryName(accessory=accessory, name=name))
    else:
        for entry in names:
            if entry.accessory == accessory:
                entry.name = name
    await client.set_accessory_names(names)
    render.console.print(f"[green]✓[/green] Accessory {accessory} renamed to {name!r}.")
