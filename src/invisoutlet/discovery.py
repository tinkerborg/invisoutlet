"""mDNS discovery for InvisOutlet devices."""

import asyncio
from dataclasses import dataclass

from zeroconf import ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf


# NOTE: the mDNS service type is not documented in the official API reference
# (which points to Home Assistant MQTT discovery instead). This value is
# reverse-engineered and unverified.
SERVICE_TYPE = "_invis._tcp.local."


@dataclass
class DiscoveredDevice:
    """An InvisOutlet device found via mDNS."""

    name: str
    host: str
    port: int
    serial_number: str
    device_type: str
    sub_type: str | None = None
    sub_device: str | None = None
    sub_sn: str | None = None


async def discover(timeout: float = 5.0) -> list[DiscoveredDevice]:
    """Scan the network for InvisOutlet devices.

    Args:
        timeout: How long to scan in seconds.

    Returns:
        List of discovered devices.

    """
    devices: dict[str, DiscoveredDevice] = {}

    def on_state_change(
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change == ServiceStateChange.Added:
            asyncio.ensure_future(_resolve(zeroconf, service_type, name, devices))

    async def _resolve(
        zc: Zeroconf,
        service_type: str,
        name: str,
        found: dict[str, DiscoveredDevice],
    ) -> None:
        info = AsyncServiceInfo(service_type, name)
        if await info.async_request(zc, 3000):
            device = _parse_service_info(info)
            if device:
                found[device.serial_number] = device

    aiozc = AsyncZeroconf()
    browser = AsyncServiceBrowser(aiozc.zeroconf, SERVICE_TYPE, handlers=[on_state_change])

    await asyncio.sleep(timeout)

    await browser.async_cancel()
    await aiozc.async_close()

    return list(devices.values())


def _parse_service_info(info: AsyncServiceInfo) -> DiscoveredDevice | None:
    """Parse a zeroconf service info into a DiscoveredDevice."""
    props = {k.decode(): v.decode() if isinstance(v, bytes) else v for k, v in info.properties.items()}

    sn = props.get("sn")
    if not sn:
        return None

    addresses = info.parsed_scoped_addresses()
    if not addresses:
        return None

    return DiscoveredDevice(
        name=info.server or info.name.split(".")[0],
        host=addresses[0],
        port=info.port or 5660,
        serial_number=sn,
        device_type=props.get("device", ""),
        sub_type=props.get("sub_type"),
        sub_device=props.get("sub_device"),
        sub_sn=props.get("sub_sn"),
    )
