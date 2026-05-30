"""Tests for mDNS service-info parsing."""

from __future__ import annotations

from typing import Any

from intecular_client.discovery import _parse_service_info


class FakeServiceInfo:
    """Minimal stand-in for zeroconf's AsyncServiceInfo."""

    def __init__(
        self,
        properties: dict[bytes, bytes | None],
        addresses: list[str],
        *,
        server: str | None = "device.local.",
        name: str = "Intecular._invis._tcp.local.",
        port: int | None = 3333,
    ) -> None:
        """Initialize the fake info."""
        self.properties = properties
        self._addresses = addresses
        self.server = server
        self.name = name
        self.port = port

    def parsed_scoped_addresses(self) -> list[str]:
        """Return the resolved addresses."""
        return self._addresses


def test_parse_full_service_info() -> None:
    """A well-formed record should parse into a DiscoveredDevice."""
    info: Any = FakeServiceInfo(
        properties={
            b"sn": b"ABC123",
            b"device": b"InvisOutlet",
            b"sub_type": b"deco",
            b"sub_sn": b"DEF456",
        },
        addresses=["10.0.0.9"],
    )
    device = _parse_service_info(info)
    assert device is not None
    assert device.serial_number == "ABC123"
    assert device.host == "10.0.0.9"
    assert device.port == 3333
    assert device.device_type == "InvisOutlet"
    assert device.sub_type == "deco"
    assert device.sub_sn == "DEF456"


def test_parse_defaults_port_when_missing() -> None:
    """A missing port should fall back to the default."""
    info: Any = FakeServiceInfo(
        properties={b"sn": b"X"}, addresses=["10.0.0.1"], port=None
    )
    device = _parse_service_info(info)
    assert device is not None
    assert device.port == 5660


def test_parse_returns_none_without_sn() -> None:
    """Records without a serial number are ignored."""
    info: Any = FakeServiceInfo(properties={b"device": b"InvisOutlet"}, addresses=["10.0.0.1"])
    assert _parse_service_info(info) is None


def test_parse_returns_none_without_address() -> None:
    """Records that resolve to no address are ignored."""
    info: Any = FakeServiceInfo(properties={b"sn": b"X"}, addresses=[])
    assert _parse_service_info(info) is None


def test_parse_falls_back_to_name_when_no_server() -> None:
    """Without a server hostname the leading name label is used."""
    info: Any = FakeServiceInfo(
        properties={b"sn": b"X"},
        addresses=["10.0.0.1"],
        server=None,
        name="MyOutlet._invis._tcp.local.",
    )
    device = _parse_service_info(info)
    assert device is not None
    assert device.name == "MyOutlet"
