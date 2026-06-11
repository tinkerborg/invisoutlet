"""The ``device`` group: main-device info and operations."""

from __future__ import annotations

import typer

from intecular_client import IntecularClient

from .. import render
from ..state import confirm_destructive, run_with_client

device_app = typer.Typer(
    name="device", help="Inspect and manage the device.", no_args_is_help=True
)
reset_app = typer.Typer(name="reset", help="Reset the device.", no_args_is_help=True)
device_app.add_typer(reset_app)


def register(app: typer.Typer) -> None:
    """Attach the ``device`` group to ``app``."""
    app.add_typer(device_app)


@device_app.command()
def info(ctx: typer.Context) -> None:
    """Show device and sub-device information."""
    run_with_client(ctx.obj, _info)


@device_app.command()
def config(ctx: typer.Context) -> None:
    """Show the full device configuration."""
    run_with_client(ctx.obj, _config)


@device_app.command()
def restart(ctx: typer.Context) -> None:
    """Restart the device."""
    run_with_client(ctx.obj, _restart)


@reset_app.command()
def network(ctx: typer.Context) -> None:
    """Reset network settings (clears Matter commissioning)."""
    confirm_destructive(ctx.obj, "reset-network")
    run_with_client(ctx.obj, _reset_network)


@reset_app.command()
def factory(ctx: typer.Context) -> None:
    """Factory-reset the device, erasing all configuration."""
    confirm_destructive(ctx.obj, "factory-reset")
    run_with_client(ctx.obj, _factory_reset)


async def _info(client: IntecularClient) -> None:
    render.render_info(await client.get_device_info())


async def _config(client: IntecularClient) -> None:
    render.render_config(await client.get_config())


async def _restart(client: IntecularClient) -> None:
    await client.restart()
    render.console.print("[green]✓[/green] Restart command sent.")


async def _reset_network(client: IntecularClient) -> None:
    await client.reset_network()
    render.console.print("[green]✓[/green] Network reset command sent.")


async def _factory_reset(client: IntecularClient) -> None:
    await client.factory_reset()
    render.console.print("[green]✓[/green] Factory reset command sent.")
