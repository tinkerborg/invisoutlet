"""The ``nightlight`` group, split by faceplate type.

``pro`` controls a plain (white) nightlight via callbacks 14/15; ``aura``
controls the color LED array via callbacks 17/18. The two are mutually
exclusive depending on the attached faceplate.
"""

from __future__ import annotations

import typer

from intecular_client import IntecularClient

from .. import render
from ..state import run_with_client

nightlight_app = typer.Typer(
    name="nightlight", help="Control the nightlight.", no_args_is_help=True
)
pro_app = typer.Typer(
    name="pro", help="Plain (white) nightlight.", no_args_is_help=True
)
aura_app = typer.Typer(
    name="aura", help="Aura (color) nightlight.", no_args_is_help=True
)
nightlight_app.add_typer(pro_app)
nightlight_app.add_typer(aura_app)

_BRIGHTNESS = typer.Option(
    100, "--bri", "--brightness", min=0, max=100, help="Brightness 0–100."
)
_OFF = typer.Option(False, "--off", help="Turn the light off.")


def register(app: typer.Typer) -> None:
    """Attach the ``nightlight`` group to ``app``."""
    app.add_typer(nightlight_app)


# --- pro: plain white nightlight (callbacks 14/15) ------------------------


@pro_app.command()
def on(ctx: typer.Context) -> None:
    """Turn the nightlight on (keeping its current brightness)."""
    run_with_client(ctx.obj, _on)


@pro_app.command()
def off(ctx: typer.Context) -> None:
    """Turn the nightlight off."""
    run_with_client(ctx.obj, _off_)


@pro_app.command()
def brightness(
    ctx: typer.Context,
    level: int = typer.Argument(..., min=0, max=100, help="Brightness 0–100."),
) -> None:
    """Set the nightlight brightness (turns it on)."""
    run_with_client(ctx.obj, lambda c: _brightness(c, level))


@pro_app.command()
def status(ctx: typer.Context) -> None:
    """Show the nightlight power state."""
    run_with_client(ctx.obj, _status)


# --- aura: color LED array (callbacks 17/18) ------------------------------


@aura_app.command()
def color(
    ctx: typer.Context,
    hue: int = typer.Argument(..., min=0, max=360, help="Hue 0–360."),
    saturation: int = typer.Argument(..., min=0, max=100, help="Saturation 0–100."),
    bri: int = _BRIGHTNESS,
    off: bool = _OFF,
) -> None:
    """Set the color (HSV)."""
    run_with_client(
        ctx.obj,
        lambda c: c.set_nightlight_color(hue, saturation, bri, not off),
    )


@aura_app.command()
def temp(
    ctx: typer.Context,
    kelvin: int = typer.Argument(
        ..., min=1000, max=40000, help="Color temperature in Kelvin."
    ),
    bri: int = _BRIGHTNESS,
    off: bool = _OFF,
) -> None:
    """Set a white color temperature."""
    run_with_client(
        ctx.obj,
        lambda c: c.set_nightlight_temperature(kelvin, bri, not off),
    )


@aura_app.command("status")
def aura_status(ctx: typer.Context) -> None:
    """Show the current per-LED state."""
    run_with_client(ctx.obj, _aura_status)


async def _on(client: IntecularClient) -> None:
    state = await client.get_nightlight()
    await client.set_nightlight(1, state.brightness or 100)
    render.console.print("[green]✓[/green] Nightlight on.")


async def _off_(client: IntecularClient) -> None:
    state = await client.get_nightlight()
    await client.set_nightlight(0, state.brightness)
    render.console.print("[green]✓[/green] Nightlight off.")


async def _brightness(client: IntecularClient, level: int) -> None:
    await client.set_nightlight(1, level)
    render.console.print(f"[green]✓[/green] Nightlight brightness {level}.")


async def _status(client: IntecularClient) -> None:
    render.render_nightlight(await client.get_nightlight())


async def _aura_status(client: IntecularClient) -> None:
    render.render_color(await client.get_nightlight_color())
