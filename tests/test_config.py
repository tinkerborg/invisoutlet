"""Tests for the CLI's default-device persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from intecular_client.cli import config
from intecular_client.cli.config import (
    DefaultDevice,
    clear_default_device,
    get_default_device,
    set_default_device,
)


@pytest.fixture(autouse=True)
def tmp_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the config path at a temporary file."""
    path = tmp_path / "cli.json"
    monkeypatch.setenv("INTECULAR_CLI_CONFIG", str(path))
    return path


def test_no_config_returns_none() -> None:
    """A missing config file yields no default device."""
    assert get_default_device() is None


def test_roundtrip() -> None:
    """A saved device is read back identically."""
    set_default_device(DefaultDevice(host="10.1.2.3", name="Lab", serial_number="SN9"))
    saved = get_default_device()
    assert saved == DefaultDevice(host="10.1.2.3", name="Lab", serial_number="SN9")


def test_set_overwrites() -> None:
    """Saving again replaces the previous default."""
    set_default_device(DefaultDevice(host="10.0.0.1"))
    set_default_device(DefaultDevice(host="10.0.0.2", name="New"))
    saved = get_default_device()
    assert saved is not None and saved.host == "10.0.0.2"


def test_clear() -> None:
    """Clearing removes the default device."""
    set_default_device(DefaultDevice(host="10.0.0.1"))
    clear_default_device()
    assert get_default_device() is None


def test_clear_when_absent_is_noop() -> None:
    """Clearing with no config present does not raise."""
    clear_default_device()
    assert get_default_device() is None


def test_corrupt_file_returns_none(tmp_config: Path) -> None:
    """A corrupt config file is tolerated as no default."""
    tmp_config.write_text("{not valid json", encoding="utf-8")
    assert get_default_device() is None


def test_preserves_unknown_keys(tmp_config: Path) -> None:
    """Saving a default leaves unrelated config keys intact."""
    tmp_config.write_text('{"other": 1}', encoding="utf-8")
    set_default_device(DefaultDevice(host="10.0.0.5"))
    import json

    data = json.loads(tmp_config.read_text(encoding="utf-8"))
    assert data["other"] == 1
    assert data["default_device"]["host"] == "10.0.0.5"
    assert config.get_default_device() is not None
