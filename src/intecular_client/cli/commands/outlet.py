"""The ``outlet`` group: control the two switched outlets."""

from __future__ import annotations

import typer

from intecular_client import IntecularClient

from .. import render
from ..state import run_with_client

outlet_app = typer.Typer(
    name="outlet", help="Control the outlets.", no_args_is_help=True
)


def register(app: typer.Typer) -> None:
    """Attach the ``outlet`` group to ``app``."""
    app.add_typer(outlet_app)


@outlet_app.command()
def on(
    ctx: typer.Context,
    outlet: int = typer.Argument(..., min=1, max=2, help="Outlet number (1 or 2)."),
) -> None:
    """Turn an outlet on."""
    run_with_client(ctx.obj, lambda c: _set(c, outlet, True))


@outlet_app.command()
def off(
    ctx: typer.Context,
    outlet: int = typer.Argument(..., min=1, max=2, help="Outlet number (1 or 2)."),
) -> None:
    """Turn an outlet off."""
    run_with_client(ctx.obj, lambda c: _set(c, outlet, False))


@outlet_app.command()
def status(ctx: typer.Context) -> None:
    """Show the on/off state of each outlet."""
    run_with_client(ctx.obj, _status)


async def _set(client: IntecularClient, outlet: int, on: bool) -> None:
    await client.set_outlet(outlet, on)
    render.console.print(
        f"[green]✓[/green] Outlet {outlet} turned {'on' if on else 'off'}."
    )


async def _status(client: IntecularClient) -> None:
    render.render_status(await client.get_outlet_status())
