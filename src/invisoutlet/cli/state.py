"""Shared CLI state and the async-to-sync command bridge.

Typer command functions are synchronous, but the underlying client is async.
Commands therefore stay tiny and synchronous, delegating their real work to an
async coroutine run through :func:`run_with_client`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import typer

from invisoutlet import InvisOutletClient, InvisOutletError

from .config import DefaultDevice, get_default_device, set_default_device
from .picker import pick_device
from .render import console


@dataclass
class CLIState:
    """Global options shared across all commands, stored on ``ctx.obj``."""

    host: str | None
    yes: bool


async def resolve_host(state: CLIState) -> str:
    """Determine which device to talk to.

    Resolution order: the explicit ``--host`` flag, then the saved default
    device, then an interactive picker. When the picker is used, the chosen
    device is offered as the new default (prompt defaults to yes).
    """
    if state.host is not None:
        return state.host

    default = get_default_device()
    if default is not None:
        return default.host

    device = await pick_device()
    if device is None:
        raise typer.Exit(code=1)

    if typer.confirm("Set as default?", default=True):
        set_default_device(
            DefaultDevice(
                host=device.host,
                name=device.name,
                serial_number=device.serial_number,
            )
        )
        console.print(f"[green]✓[/green] Saved {device.name} as the default device.")
    return device.host


def run_with_client(
    state: CLIState, body: Callable[[InvisOutletClient], Awaitable[None]]
) -> None:
    """Open a client, run an async command body, then close cleanly.

    Bridges Typer's synchronous commands to the async client and swallows
    ``Ctrl+C`` so the tool exits quietly rather than dumping a traceback.
    """

    async def _main() -> None:
        host = await resolve_host(state)
        async with InvisOutletClient(host) as client:
            await body(client)

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
    except InvisOutletError as err:
        console.print(f"[red]Error:[/red] {err}")
        raise typer.Exit(code=1) from err


def confirm_destructive(state: CLIState, action: str) -> None:
    """Prompt for confirmation before a destructive action.

    Skipped when the global ``--yes`` flag was passed. Aborts the command
    (raising ``typer.Abort``) if the user declines.
    """
    if not state.yes:
        typer.confirm(
            f"{action!r} is destructive and cannot be undone. Continue?",
            abort=True,
        )
