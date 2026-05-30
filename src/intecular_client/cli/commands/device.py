"""The ``device`` group: main-device info and operations."""

from __future__ import annotations

import asyncio

import typer

from intecular_client import IntecularClient
from intecular_client.models import OtaResult

from .. import render
from ..state import confirm_destructive, run_with_client

device_app = typer.Typer(
    name="device", help="Inspect and manage the device.", no_args_is_help=True
)
reset_app = typer.Typer(name="reset", help="Reset the device.", no_args_is_help=True)
firmware_app = typer.Typer(
    name="firmware", help="Firmware updates.", no_args_is_help=True
)
device_app.add_typer(reset_app)
device_app.add_typer(firmware_app)


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


@firmware_app.command()
def check(ctx: typer.Context) -> None:
    """Show available firmware updates."""
    run_with_client(ctx.obj, _firmware_check)


@firmware_app.command()
def update(
    ctx: typer.Context,
    target: int = typer.Argument(..., help="Target device (0 = outlet, 1 = deco)."),
    method: int = typer.Option(0, "--method", help="Update method identifier."),
) -> None:
    """Start an OTA update and stream progress until it completes."""
    run_with_client(ctx.obj, lambda c: _firmware_update(c, target, method))


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


async def _firmware_check(client: IntecularClient) -> None:
    render.render_updates(await client.get_available_updates())


async def _firmware_update(client: IntecularClient, target: int, method: int) -> None:
    done = asyncio.Event()

    client.on_ota_progress(
        lambda p: render.console.print(f"  device {p.device}: {p.progress}%")
    )

    def on_result(result: OtaResult) -> None:
        marker = "[green]✓[/green]" if result.success else "[red]✗[/red]"
        render.console.print(f"{marker} OTA result for device {result.device}.")
        done.set()

    client.on_ota_result(on_result)

    render.console.print(f"Starting OTA for device {target} (method {method})…")
    await client.perform_ota_update(target, method)
    try:
        await asyncio.wait_for(done.wait(), timeout=600)
    except TimeoutError:
        render.console.print("[yellow]Timed out waiting for OTA result.[/yellow]")
