"""On-disk persistence for the CLI's default device.

Stored as JSON at ``~/.invis_cli.json`` (override with the
``INVIS_CLI_CONFIG`` environment variable, primarily for tests).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

_DEFAULT_DEVICE_KEY = "default_device"


def config_path() -> Path:
    """Return the config file path, honoring ``INVIS_CLI_CONFIG``.

    Resolved on each call so tests can point it at a temporary file.
    """
    override = os.environ.get("INVIS_CLI_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".invis_cli.json"


@dataclass
class DefaultDevice:
    """The persisted default device. Only ``host`` is required to connect."""

    host: str
    name: str | None = None
    serial_number: str | None = None


def _read() -> dict:
    """Load the raw config dict, tolerating a missing or corrupt file."""
    path = config_path()
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    """Persist the raw config dict, creating parent directories as needed."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def get_default_device() -> DefaultDevice | None:
    """Return the saved default device, or ``None`` if none is set."""
    raw = _read().get(_DEFAULT_DEVICE_KEY)
    if not isinstance(raw, dict) or "host" not in raw:
        return None
    return DefaultDevice(
        host=raw["host"],
        name=raw.get("name"),
        serial_number=raw.get("serial_number"),
    )


def set_default_device(device: DefaultDevice) -> None:
    """Persist ``device`` as the default, leaving any other keys intact."""
    data = _read()
    data[_DEFAULT_DEVICE_KEY] = asdict(device)
    _write(data)


def clear_default_device() -> None:
    """Remove the saved default device, if any."""
    data = _read()
    if data.pop(_DEFAULT_DEVICE_KEY, None) is not None:
        _write(data)
