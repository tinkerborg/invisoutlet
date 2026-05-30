"""The flat ``discover`` command: scan the local network via mDNS."""

from __future__ import annotations

import asyncio

import typer

from intecular_client import discover

from .. import render


def register(app: typer.Typer) -> None:
    """Attach the ``discover`` command to ``app``."""

    @app.command(name="discover")
    def discover_devices(
        timeout: float = typer.Option(5.0, "--timeout", help="Scan duration in seconds."),
    ) -> None:
        """Scan the local network for Intecular devices via mDNS."""
        # Discovery needs no device connection, so it bypasses run_with_client.
        async def _run() -> None:
            render.render_discovered(await discover(timeout))

        try:
            asyncio.run(_run())
        except KeyboardInterrupt:
            pass
