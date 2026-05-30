"""Command-line interface for the Intecular client.

The console entry point ``intecular`` resolves to :data:`app`.
"""

from .app import app

__all__ = ["app"]
