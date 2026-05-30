"""The ``watch`` command: a live-updating stream of sensor data."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Group, RenderableType
from rich.live import Live
from rich.text import Text

from intecular_client import IntecularClient, SensorData

from ..render import console, sensor_table
from ..state import run_with_client

_HINT = Text("Ctrl+C to exit", style="dim")


def _frame(body: RenderableType) -> Group:
    """Stack the body above a persistent exit hint for the live view."""
    return Group(body, Text(), _HINT)


def register(app: typer.Typer) -> None:
    """Attach the ``watch`` command to ``app``."""

    @app.command()
    def watch(
        ctx: typer.Context,
        us: bool = typer.Option(
            False,
            "--us",
            help="Show temperature, pressure and distance in US customary units.",
        ),
    ) -> None:
        """Stream live sensor data until interrupted (Ctrl+C)."""
        run_with_client(ctx.obj, lambda client: _watch(client, us))


async def _watch(client: IntecularClient, us: bool) -> None:
    """Drive a Rich ``Live`` table from the sensor-data callback."""
    info = await client.get_device_info()

    with Live(console=console, auto_refresh=False, screen=True) as live:
        def on_sensors(data: SensorData) -> None:
            live.update(_frame(sensor_table(info, data, us)), refresh=True)

        client.on_sensor_data(on_sensors)
        live.update(
            _frame(Text("Waiting for sensor data…", style="dim")), refresh=True
        )
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass
