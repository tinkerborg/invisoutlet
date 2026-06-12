"""Command-line interface for the InvisOutlet client.

The console entry point ``invis`` resolves to :data:`app`.
"""

from .app import app

__all__ = ["app"]
