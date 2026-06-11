"""Data models for Intecular devices."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Self


def wire(*path: str, bool_int: bool = False) -> Any:
    """Define a field that maps to a nested wire protocol path.

    Args:
        *path: Keys to traverse in the nested wire format.
        bool_int: If True, convert between Python bool and wire int (0/1).

    """
    return field(default=None, metadata={"wire_path": path, "bool_int": bool_int})


@dataclass
class WireModel:
    """Base for dataclasses that map flat fields to nested wire format."""

    def to_raw(self) -> dict[str, Any]:
        """Convert to nested wire format, omitting None values."""
        result: dict[str, Any] = {}
        for f in fields(self):
            wire_path = f.metadata.get("wire_path")
            if wire_path is None:
                continue
            val = getattr(self, f.name)
            if val is None:
                continue
            if f.metadata.get("bool_int"):
                val = int(val)
            target = result
            for key in wire_path[:-1]:
                target = target.setdefault(key, {})
            target[wire_path[-1]] = val
        return result

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> Self:
        """Create from nested wire format."""
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            wire_path = f.metadata.get("wire_path")
            if wire_path is None:
                continue
            val: Any = data
            for key in wire_path:
                if not isinstance(val, dict):
                    val = None
                    break
                val = val.get(key)
            if val is None:
                continue
            if f.metadata.get("bool_int"):
                val = bool(val)
            kwargs[f.name] = val
        return cls(**kwargs)


@dataclass
class SensorData:
    """Sensor readings from an Intecular outlet."""

    temperature: float | None = None
    humidity: float | None = None
    air_quality_index: int | None = None
    co2: int | None = None
    voc: float | None = None
    pressure: float | None = None
    illuminance: float | None = None
    distance: int | None = None
    occupancy_state: int | None = None
    movement_energy: int | None = None
    stationary_energy: int | None = None
    gas: int | None = None
    aqi_accuracy: int | None = None
    # Undocumented field observed on real hardware (firmware drift from the docs).
    temp_humidity_accuracy: int | None = None
    co2_peak: int | None = None
    co2_accuracy: int | None = None
    voc_accuracy: int | None = None
    # Development-only raw BME680 readings.
    bme680_temperature: float | None = None
    bme680_humidity: float | None = None
    # Validity flags reported alongside the readings.
    temp_valid: bool | None = None
    aqi_valid: bool | None = None
    lux_valid: bool | None = None
    occupancy_valid: bool | None = None

    @property
    def occupancy(self) -> bool | None:
        """Whether occupancy is detected."""
        if self.occupancy_state is None:
            return None
        return self.occupancy_state > 0

    @property
    def motion(self) -> bool | None:
        """Whether motion is detected."""
        if self.movement_energy is None:
            return None
        return self.movement_energy > 0

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> SensorData:
        """Create from raw API response."""
        return cls(
            temperature=_float_or_none(data.get("temp_celsius")),
            humidity=_float_or_none(data.get("humidity")),
            air_quality_index=_int_or_none(data.get("AQI")),
            co2=_int_or_none(data.get("co2_equiv")),
            voc=_float_or_none(data.get("bvoc_equiv")),
            pressure=_int_or_none(data.get("pressure")),
            illuminance=_float_or_none(data.get("lux")),
            distance=_int_or_none(data.get("distance")),
            occupancy_state=_int_or_none(data.get("occupancy_state")),
            movement_energy=_int_or_none(data.get("movement_energy")),
            stationary_energy=_int_or_none(data.get("stationary_energy")),
            gas=_int_or_none(data.get("gas")),
            aqi_accuracy=_int_or_none(data.get("AQI_accuracy")),
            temp_humidity_accuracy=_int_or_none(data.get("temphumidity_accuracy")),
            co2_peak=_int_or_none(data.get("co2_peak_lvl")),
            co2_accuracy=_int_or_none(data.get("co2_accuracy")),
            voc_accuracy=_int_or_none(data.get("bvoc_accuracy")),
            bme680_temperature=_float_or_none(data.get("BME680_temp_celsius")),
            bme680_humidity=_float_or_none(data.get("BME680_humidity")),
            temp_valid=_bool_or_none(data.get("temp_valid")),
            aqi_valid=_bool_or_none(data.get("aqi_valid")),
            lux_valid=_bool_or_none(data.get("lux_valid")),
            occupancy_valid=_bool_or_none(data.get("occupancy_valid")),
        )


@dataclass
class SubDeviceInfo:
    """Information about an attached sub-device (e.g. InvisDeco)."""

    serial_number: str
    mac: str
    device: str
    device_type: str | None = None
    hw_rev: str | None = None
    fw_rev: str | None = None
    online: bool = False
    radar_fw_ver: str | None = None
    radar_hw_type: str | None = None
    radar_mac: str | None = None


@dataclass
class DeviceInfo:
    """Device information for an Intecular outlet."""

    serial_number: str
    mac: str
    device: str
    hw_rev: str | None = None
    fw_rev: str | None = None
    host: str = ""
    port: int = 3333
    sub_device: SubDeviceInfo | None = None

    @classmethod
    def from_raw(cls, data: dict[str, Any], host: str = "", port: int = 3333) -> DeviceInfo:
        """Create from raw API response."""
        im = data.get("IM", {})
        pm = data.get("PM")

        sub_device = None
        if pm:
            radar = pm.get("radar", {})
            sub_device = SubDeviceInfo(
                serial_number=pm.get("sn", ""),
                mac=pm.get("MAC", ""),
                device=pm.get("device", ""),
                device_type=pm.get("type"),
                hw_rev=pm.get("hw_rev"),
                fw_rev=pm.get("fw_rev"),
                online=pm.get("online", False),
                radar_fw_ver=radar.get("fw_ver"),
                radar_hw_type=radar.get("hw_type"),
                radar_mac=radar.get("MAC"),
            )

        return cls(
            serial_number=im.get("sn", ""),
            mac=im.get("MAC", ""),
            device=im.get("device", ""),
            hw_rev=im.get("hw_rev"),
            fw_rev=im.get("fw_rev"),
            host=host,
            port=port,
            sub_device=sub_device,
        )


@dataclass
class DeviceConfig(WireModel):
    """Device configuration."""

    # Accessory preferences
    outlet_power_indicator_on: bool | None = wire("acc_prefs", "outletPwrIndicatorOn", bool_int=True)
    pm_indicator_brightness: int | None = wire("acc_prefs", "pmIndicatorBrightness")
    capacitive_ctrl: bool | None = wire("acc_prefs", "capacitiveCtrl", bool_int=True)
    aqi_color_rgb_feature: bool | None = wire("acc_prefs", "aqiColorRGBFeature", bool_int=True)
    motion_away_feature: bool | None = wire("acc_prefs", "motionAwayFeature", bool_int=True)
    adaptive_nightlight_feature: bool | None = wire("acc_prefs", "adaptiveNightlightFeature", bool_int=True)
    adaptive_min_brightness: int | None = wire("acc_prefs", "adaptiveMinBrightness")
    adaptive_max_brightness: int | None = wire("acc_prefs", "adaptiveMaxBrightness")
    occupancy_nightlight_feature: bool | None = wire("acc_prefs", "occupancyNightlightFeature", bool_int=True)
    override_adaptive_occupancy_nightlight_feature: bool | None = wire("acc_prefs", "overrideAdaptiveOccupancyNightlightFeature", bool_int=True)
    magic_touch_ctrl: bool | None = wire("acc_prefs", "magicTouchCtrl", bool_int=True)

    # Home/Away simulation
    home_away_enabled: bool | None = wire("acc_prefs", "homeAwayMode", "enabled", bool_int=True)
    home_away_outlet1_enabled: bool | None = wire("acc_prefs", "homeAwayMode", "outlet1Enabled", bool_int=True)
    home_away_outlet2_enabled: bool | None = wire("acc_prefs", "homeAwayMode", "outlet2Enabled", bool_int=True)
    home_away_nightlight_enabled: bool | None = wire("acc_prefs", "homeAwayMode", "nightlightEnabled", bool_int=True)
    home_away_min_brightness: int | None = wire("acc_prefs", "homeAwayMode", "minBrightness")
    home_away_max_brightness: int | None = wire("acc_prefs", "homeAwayMode", "maxBrightness")
    home_away_min_on_duration: int | None = wire("acc_prefs", "homeAwayMode", "minOnDuration")
    home_away_max_on_duration: int | None = wire("acc_prefs", "homeAwayMode", "maxOnDuration")
    home_away_min_off_duration: int | None = wire("acc_prefs", "homeAwayMode", "minOffDuration")
    home_away_max_off_duration: int | None = wire("acc_prefs", "homeAwayMode", "maxOffDuration")

    # MQTT settings
    mqtt_enabled: bool | None = wire("sys_prefs", "mqtt", "enabled", bool_int=True)
    mqtt_broker_url: str | None = wire("sys_prefs", "mqtt", "mqtt_broker_url")
    mqtt_user: str | None = wire("sys_prefs", "mqtt", "user")
    mqtt_password: str | None = wire("sys_prefs", "mqtt", "pass")
    mqtt_qos: int | None = wire("sys_prefs", "mqtt", "qos")

    # Network info (read-only; reported by the device, not settable)
    internet_ip: str | None = wire("sys_prefs", "internet", "ip")
    internet_main_dns: str | None = wire("sys_prefs", "internet", "mainDNS")
    internet_backup_dns: str | None = wire("sys_prefs", "internet", "backupDNS")


@dataclass
class AccessoryName:
    """A user-assigned label for an accessory (outlet or nightlight)."""

    accessory: int
    name: str

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> AccessoryName:
        """Create from raw API response."""
        return cls(accessory=int(data["accessory"]), name=str(data["name"]))

    def to_raw(self) -> dict[str, Any]:
        """Convert to wire format."""
        return {"accessory": self.accessory, "name": self.name}


@dataclass
class OutletStatus:
    """On/off state of each outlet, indexed from outlet 1."""

    outlets: list[bool]

    def is_on(self, outlet: int) -> bool:
        """Return whether the given 1-based outlet is on."""
        return self.outlets[outlet - 1]

    @classmethod
    def from_raw(cls, args: list[Any]) -> OutletStatus:
        """Create from the positional response array, e.g. [1, 0]."""
        return cls(outlets=[bool(v) for v in args])


@dataclass
class NightlightState:
    """Nightlight mode and brightness."""

    mode: int
    brightness: int

    @property
    def on(self) -> bool:
        """Whether the nightlight is active."""
        return self.mode > 0

    @classmethod
    def from_raw(cls, args: list[Any]) -> NightlightState:
        """Create from the positional array [mode, brightness]."""
        return cls(mode=int(args[0]), brightness=int(args[1]))

    def to_raw(self) -> list[Any]:
        """Convert to the positional array [mode, brightness]."""
        return [self.mode, self.brightness]


@dataclass
class ColorLedEntry:
    """A single LED entry within a color light.

    For static-temperature control only ``temperature`` is used; full color
    state additionally carries ``hue``/``saturation``.
    """

    state: bool
    brightness: int
    temperature: int | None = None
    hue: int | None = None
    saturation: int | None = None


@dataclass
class ColorLightState:
    """State of an addressable color light (e.g. InvisDeco Aura)."""

    light: int
    mode: int
    leds: list[ColorLedEntry]

    @classmethod
    def from_raw(cls, args: list[Any]) -> ColorLightState:
        """Parse a callback 18 response.

        Shape: ``[light, mode, [<led>, ...]]``. An LED entry is
        ``[state, brightness, ...]`` whose trailing fields vary by array: an
        ``[hue, sat]`` pair and/or a kelvin int may appear, in any combination
        (the nightlight reports both; the indicator reports fewer).
        """
        light, mode, entries = args[0], args[1], args[2]
        leds: list[ColorLedEntry] = []
        for entry in entries:
            state, brightness, *rest = entry
            hue = saturation = temperature = None
            for value in rest:
                if isinstance(value, list) and len(value) >= 2:
                    hue, saturation = int(value[0]), int(value[1])
                elif isinstance(value, (int, float)):
                    temperature = int(value)
            leds.append(
                ColorLedEntry(
                    state=bool(state),
                    brightness=int(brightness),
                    hue=hue,
                    saturation=saturation,
                    temperature=temperature,
                )
            )
        return cls(light=int(light), mode=int(mode), leds=leds)

    def to_temperature_raw(self) -> list[Any]:
        """Serialize for callback 17 (static temperature).

        Shape: ``[light, mode, [[state, brightness, kelvin], ...]]``.
        """
        entries = [
            [int(led.state), led.brightness, led.temperature] for led in self.leds
        ]
        return [self.light, self.mode, entries]

    def to_hsv_raw(self) -> list[Any]:
        """Serialize for callback 17 (static HSV).

        Shape: ``[light, mode, [[state, brightness, [hue, saturation]], ...]]``.
        """
        entries = [
            [int(led.state), led.brightness, [led.hue, led.saturation]]
            for led in self.leds
        ]
        return [self.light, self.mode, entries]


@dataclass
class FirmwareUpdate:
    """Installed and available firmware revisions for a single module."""

    fw_rev: str | None = None
    available_fw_rev: str | None = None
    www_fw_rev: str | None = None
    available_www_fw_rev: str | None = None

    @property
    def update_available(self) -> bool:
        """Whether a newer firmware revision is available."""
        return (
            self.available_fw_rev is not None
            and self.available_fw_rev != self.fw_rev
        ) or (
            self.available_www_fw_rev is not None
            and self.available_www_fw_rev != self.www_fw_rev
        )

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> FirmwareUpdate:
        """Create from raw API response."""
        return cls(
            fw_rev=data.get("fw_rev"),
            available_fw_rev=data.get("available_fw_rev"),
            www_fw_rev=data.get("www_fw_rev"),
            available_www_fw_rev=data.get("available_www_fw_rev"),
        )


@dataclass
class AvailableUpdates:
    """Available firmware updates for the outlet (IM) and sub-device (PM)."""

    im: FirmwareUpdate
    pm: FirmwareUpdate | None = None

    @property
    def update_available(self) -> bool:
        """Whether any module has an update available."""
        return self.im.update_available or (
            self.pm is not None and self.pm.update_available
        )

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> AvailableUpdates:
        """Create from a callback 20 response."""
        pm = data.get("PM")
        return cls(
            im=FirmwareUpdate.from_raw(data.get("IM", {})),
            pm=FirmwareUpdate.from_raw(pm) if pm else None,
        )


@dataclass
class FirmwareRelease:
    """A firmware release from the Intecular update service.

    Returned by the OTA-check endpoint for a single module: the latest available
    revision, its download URL and the release notes (``message``).
    """

    current_fw_rev: str
    available_fw_rev: str
    ota_bin_url: str
    message: str

    @property
    def update_available(self) -> bool:
        """Whether the available revision differs from the installed one."""
        return bool(self.available_fw_rev) and (
            self.available_fw_rev != self.current_fw_rev
        )

    @classmethod
    def from_raw(cls, data: dict[str, Any], current_fw_rev: str) -> FirmwareRelease:
        """Create from an OTA-check response, given the installed revision."""
        return cls(
            current_fw_rev=current_fw_rev,
            available_fw_rev=data.get("available_fw_rev", ""),
            ota_bin_url=data.get("ota_bin_url", ""),
            message=data.get("message", ""),
        )


@dataclass
class OtaProgress:
    """A server-pushed OTA download progress update (callback 22)."""

    # 1 = InvisOutlet, 2 = InvisDeco, 3 = InvisOutlet (WWW partition).
    device_type: int
    progress: int

    @classmethod
    def from_raw(cls, args: list[Any]) -> OtaProgress:
        """Parse a callback 22 push, shape ``[device_type, progress]``."""
        return cls(device_type=int(args[0]), progress=int(args[1]))


@dataclass
class OtaResult:
    """A server-pushed OTA result update (callback 23)."""

    # 1 = InvisOutlet, 2 = InvisDeco, 3 = InvisOutlet (WWW partition).
    device_type: int
    status: int

    @property
    def success(self) -> bool:
        """Whether the OTA update succeeded (status 1 = success, 0 = fail)."""
        return self.status > 0

    @classmethod
    def from_raw(cls, args: list[Any]) -> OtaResult:
        """Parse a callback 23 push, shape ``[device_type, status]``."""
        return cls(device_type=int(args[0]), status=int(args[1]))


def _bool_or_none(val: Any) -> bool | None:
    """Convert a value to bool or None, accepting JSON bool or 0/1."""
    if val is None:
        return None
    return bool(val)


def _float_or_none(val: Any) -> float | None:
    """Convert a value to float or None."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _int_or_none(val: Any) -> int | None:
    """Convert a value to int or None."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
