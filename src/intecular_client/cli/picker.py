"""Interactive device picker backed by mDNS discovery.

Kept free of any dependency on :mod:`intecular_client.cli.state` so that
``state`` can import from here without a cycle.
"""

from __future__ import annotations

import sys

import questionary
import typer

from intecular_client import DiscoveredDevice, discover

from .render import console

# Match the CLI's Rich theme by using ANSI palette names (same colors as the
# [cyan]/[green] markup elsewhere). The active row gets a cyan highlight bar;
# pointer and row text share the background so the bar is continuous.
_PICKER_STYLE = questionary.Style.from_dict(
    {
        "qmark": "fg:ansicyan bold",
        "question": "bold",
        "pointer": "fg:ansiblack bg:ansicyan bold",
        "highlighted": "fg:ansiblack bg:ansicyan bold",
        "selected": "fg:ansigreen bold",
        "answer": "fg:ansigreen bold",
        "instruction": "fg:ansibrightblack",
    }
)


def _is_interactive() -> bool:
    """Whether we have a real terminal to drive the arrow-key menu."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _label(device: DiscoveredDevice) -> str:
    """Human-readable one-line label for a discovered device."""
    return f"{device.name}  ({device.host})  {device.serial_number}"


async def pick_device(timeout: float = 5.0) -> DiscoveredDevice | None:
    """Discover devices and let the user choose one interactively.

    Requires a terminal: the picker only makes sense with a TTY. Without one
    (piped/headless), this errors out — the caller should have supplied
    ``--host`` or a saved default instead.

    Returns the chosen device, or ``None`` if discovery found nothing. A single
    discovered device is selected automatically; multiple devices are presented
    as an arrow-key menu.
    """
    if not _is_interactive():
        console.print(
            "[red]No device selected.[/red] Pass [cyan]--host[/cyan], set a default "
            "with [cyan]intecular device select[/cyan], or run in an interactive "
            "terminal."
        )
        raise typer.Exit(code=1)

    console.print(f"Scanning for devices ({timeout:.0f}s)…")
    devices = await discover(timeout)

    if not devices:
        console.print(
            "[yellow]No devices found — are you on the same VLAN as the devices?"
            "[/yellow]"
        )
        return None

    if len(devices) == 1:
        only = devices[0]
        console.print(f"Using the only device found: {only.name} ([cyan]{only.host}[/cyan])")
        return only

    choice = await questionary.select(
        "Select a device",
        choices=[questionary.Choice(title=_label(d), value=d) for d in devices],
        style=_PICKER_STYLE,
        pointer="❯",
        qmark="",
    ).ask_async()
    if choice is None:  # user pressed Ctrl-C / Esc
        raise typer.Exit(code=1)
    return choice
