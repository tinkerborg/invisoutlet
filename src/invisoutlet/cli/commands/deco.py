"""The ``deco`` group: control the attached InvisDeco faceplate."""

from __future__ import annotations

import typer

from invisoutlet import InvisOutletClient

from .. import render
from ..state import confirm_destructive, run_with_client

deco_app = typer.Typer(
    name="deco", help="Control the attached InvisDeco faceplate.", no_args_is_help=True
)
calibrate_app = typer.Typer(
    name="calibrate", help="Calibrate the faceplate's sensors.", no_args_is_help=True
)
deco_app.add_typer(calibrate_app)


def register(app: typer.Typer) -> None:
    """Attach the ``deco`` group to ``app``."""
    app.add_typer(deco_app)


@deco_app.command()
def restart(ctx: typer.Context) -> None:
    """Restart the InvisDeco."""
    run_with_client(ctx.obj, _restart)


@deco_app.command()
def reset(ctx: typer.Context) -> None:
    """Reset the InvisDeco (clears air-quality calibration)."""
    confirm_destructive(ctx.obj, "deco-reset")
    run_with_client(ctx.obj, _reset)


@calibrate_app.command()
def occupancy(
    ctx: typer.Context,
    seconds: int = typer.Argument(..., help="Calibration duration in seconds."),
) -> None:
    """Run occupancy-sensor calibration."""
    run_with_client(ctx.obj, lambda c: _calibrate_occupancy(c, seconds))


@calibrate_app.command()
def climate(
    ctx: typer.Context,
    temperature: float = typer.Argument(..., help="Reference temperature in °C."),
    humidity: float = typer.Argument(..., help="Reference relative humidity in %."),
) -> None:
    """Calibrate temperature and humidity to reference values."""
    run_with_client(ctx.obj, lambda c: _calibrate_climate(c, temperature, humidity))


async def _restart(client: InvisOutletClient) -> None:
    await client.restart_invisdeco()
    render.console.print("[green]✓[/green] InvisDeco restart command sent.")


async def _reset(client: InvisOutletClient) -> None:
    await client.reset_invisdeco()
    render.console.print("[green]✓[/green] InvisDeco reset command sent.")


async def _calibrate_occupancy(client: InvisOutletClient, seconds: int) -> None:
    await client.calibrate_occupancy(seconds)
    render.console.print(f"[green]✓[/green] Occupancy calibration started for {seconds}s.")


async def _calibrate_climate(
    client: InvisOutletClient, temperature: float, humidity: float
) -> None:
    await client.calibrate_temp_humidity(temperature, humidity)
    render.console.print(f"[green]✓[/green] Calibrated to {temperature} °C / {humidity}% RH.")
