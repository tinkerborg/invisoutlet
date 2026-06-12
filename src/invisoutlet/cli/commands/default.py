"""The ``default`` group: manage the persisted default device."""

from __future__ import annotations

import asyncio

import typer

from invisoutlet import InvisOutletClient, InvisOutletError

from ..config import (
    DefaultDevice,
    clear_default_device,
    get_default_device,
    set_default_device,
)
from ..picker import pick_device
from ..render import console

default_app = typer.Typer(
    name="default",
    help="Manage the default device.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Attach the ``default`` group to ``app``."""
    app.add_typer(default_app)


@default_app.command()
def select(
    host: str | None = typer.Option(
        None, "--host", help="Set this IP directly instead of running the picker."
    ),
) -> None:
    """Choose a device (via picker, or --host) and save it as the default."""
    if host is not None:
        device = asyncio.run(_probe(host))
    else:
        chosen = asyncio.run(pick_device())
        if chosen is None:
            raise typer.Exit(code=1)
        device = DefaultDevice(
            host=chosen.host,
            name=chosen.name,
            serial_number=chosen.serial_number,
        )

    set_default_device(device)
    console.print(
        f"[green]✓[/green] Default device set: {device.name or device.host} "
        f"([cyan]{device.host}[/cyan])."
    )


@default_app.command()
def show() -> None:
    """Show the saved default device."""
    default = get_default_device()
    if default is None:
        console.print("No default device set.")
        return
    console.print(f"Host:   [cyan]{default.host}[/cyan]")
    console.print(f"Name:   {default.name or '—'}")
    console.print(f"Serial: {default.serial_number or '—'}")


@default_app.command()
def forget() -> None:
    """Forget the saved default device."""
    clear_default_device()
    console.print("[green]✓[/green] Default device cleared.")


async def _probe(host: str) -> DefaultDevice:
    """Best-effort fetch of a device's name/serial for the saved entry.

    Falls back to just the host if the device cannot be reached.
    """
    try:
        async with InvisOutletClient(host) as client:
            info = await client.get_device_info()
    except InvisOutletError:
        return DefaultDevice(host=host)
    return DefaultDevice(
        host=host, name=info.device or None, serial_number=info.serial_number or None
    )
