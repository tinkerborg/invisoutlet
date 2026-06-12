"""The ``ota`` group: firmware update checks and installs."""

from __future__ import annotations

import asyncio
from enum import Enum

import typer

from invisoutlet import InvisOutletClient, OtaTarget
from invisoutlet.models import OtaResult

from .. import render
from ..state import run_with_client

ota_app = typer.Typer(name="ota", help="Firmware updates.", no_args_is_help=True)


class _Target(str, Enum):
    """Which module to update (named so callers don't pass raw indices)."""

    outlet = "outlet"
    deco = "deco"


class _Method(str, Enum):
    """How a faceplate update is delivered (ignored for the outlet)."""

    wifi = "wifi"
    via_outlet = "via-outlet"


_TARGETS = {_Target.outlet: OtaTarget.INVISOUTLET, _Target.deco: OtaTarget.INVISDECO}
_METHODS = {_Method.wifi: 0, _Method.via_outlet: 1}


def register(app: typer.Typer) -> None:
    """Attach the ``ota`` group to ``app``."""
    app.add_typer(ota_app)


@ota_app.command()
def check(ctx: typer.Context) -> None:
    """Show available firmware updates."""
    run_with_client(ctx.obj, _check)


@ota_app.command()
def update(
    ctx: typer.Context,
    target: _Target = typer.Argument(..., help="Which module to update."),
    method: _Method = typer.Option(
        _Method.wifi, "--method", help="Delivery method (faceplate only)."
    ),
) -> None:
    """Start an OTA update and stream progress until it completes."""
    run_with_client(
        ctx.obj, lambda c: _update(c, _TARGETS[target], _METHODS[method])
    )


async def _check(client: InvisOutletClient) -> None:
    render.render_updates(await client.get_available_updates())


async def _update(client: InvisOutletClient, target: OtaTarget, method: int) -> None:
    done = asyncio.Event()

    client.on_ota_progress(
        lambda p: render.console.print(f"  device {p.device_type}: {p.progress}%")
    )

    def on_result(result: OtaResult) -> None:
        marker = "[green]✓[/green]" if result.success else "[red]✗[/red]"
        render.console.print(f"{marker} OTA result for device {result.device_type}.")
        done.set()

    client.on_ota_result(on_result)

    render.console.print(f"Starting OTA for device {target} (method {method})…")
    await client.perform_ota_update(target, method)
    try:
        await asyncio.wait_for(done.wait(), timeout=600)
    except TimeoutError:
        render.console.print("[yellow]Timed out waiting for OTA result.[/yellow]")
