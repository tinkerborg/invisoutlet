"""Python client library for Intecular smart outlets."""

from .client import IntecularClient, OtaTarget
from .discovery import DiscoveredDevice, discover
from .exceptions import (
    IntecularCommandError,
    IntecularConnectionError,
    IntecularError,
    IntecularTimeoutError,
)
from .models import (
    AccessoryName,
    AvailableUpdates,
    ColorLedEntry,
    ColorLightState,
    DeviceConfig,
    DeviceInfo,
    FirmwareUpdate,
    NightlightState,
    OtaProgress,
    OtaResult,
    OutletStatus,
    SensorData,
    SubDeviceInfo,
)

__all__ = [
    "AccessoryName",
    "AvailableUpdates",
    "ColorLedEntry",
    "ColorLightState",
    "DeviceConfig",
    "DeviceInfo",
    "DiscoveredDevice",
    "FirmwareUpdate",
    "IntecularClient",
    "IntecularCommandError",
    "IntecularConnectionError",
    "IntecularError",
    "IntecularTimeoutError",
    "NightlightState",
    "OtaProgress",
    "OtaResult",
    "OtaTarget",
    "OutletStatus",
    "SensorData",
    "SubDeviceInfo",
    "discover",
]
