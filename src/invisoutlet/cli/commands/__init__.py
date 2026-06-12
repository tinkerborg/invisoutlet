"""Command groups for the InvisOutlet CLI.

Each module exposes a ``register(app)`` function that attaches its commands to
the shared Typer app — most as noun subgroups (`device`, `nightlight`, …), a few
as flat top-level commands (`watch`, `discover`).
"""

from . import (
    deco,
    default,
    device,
    discover,
    name,
    nightlight,
    ota,
    outlet,
    watch,
)


def register_all(app: object) -> None:
    """Register every command module against the Typer ``app``."""
    default.register(app)
    device.register(app)
    nightlight.register(app)
    outlet.register(app)
    deco.register(app)
    name.register(app)
    discover.register(app)
    ota.register(app)
    watch.register(app)


__all__ = ["register_all"]
