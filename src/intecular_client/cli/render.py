"""Rich rendering helpers for read commands.

Each ``render_*`` helper prints to the shared :data:`console`; ``sensor_table``
returns a renderable so the ``watch`` command can drive a live display.
"""

from __future__ import annotations

from collections.abc import Iterable

from rich import box
from rich.console import Console
from rich.table import Table

from intecular_client import (
    AccessoryName,
    AvailableUpdates,
    ColorLightState,
    DeviceConfig,
    DeviceInfo,
    DiscoveredDevice,
    NightlightState,
    OutletStatus,
    SensorData,
)

from .formatters import fmt_distance, fmt_pressure, fmt_temperature

console = Console()


def _kv_table(title: str) -> Table:
    """Create a two-column key/value table."""
    table = Table(title=title, title_justify="left", box=box.SIMPLE, show_header=False)
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")
    return table


def _bool(value: bool | None) -> str:
    """Render an optional bool as a colorful yes/no."""
    if value is None:
        return "—"
    return "[green]yes[/green]" if value else "[red]no[/red]"


def _text(value: object) -> str:
    """Render an optional value as a string (Rich needs a renderable, not an int)."""
    return "—" if value is None or value == "" else str(value)


def render_info(info: DeviceInfo) -> None:
    """Render device information."""
    table = _kv_table("Device")
    table.add_row("Serial number", info.serial_number)
    table.add_row("MAC", info.mac)
    table.add_row("Device", info.device)
    table.add_row("Hardware rev", info.hw_rev or "—")
    table.add_row("Firmware rev", info.fw_rev or "—")
    table.add_row("Address", f"{info.host}:{info.port}")
    console.print(table)

    sub = info.sub_device
    if sub:
        sub_table = _kv_table("Sub-device")
        sub_table.add_row("Device", f"{sub.device} ({sub.device_type or '?'})")
        sub_table.add_row("Serial number", sub.serial_number)
        sub_table.add_row("Online", _bool(sub.online))
        if sub.radar_fw_ver:
            sub_table.add_row("Radar", f"{sub.radar_hw_type} fw {sub.radar_fw_ver}")
        console.print(sub_table)


def render_config(config: DeviceConfig) -> None:
    """Render device configuration, grouped into sections."""
    prefs = _kv_table("Accessory preferences")
    prefs.add_row("Outlet power indicator", _bool(config.outlet_power_indicator_on))
    prefs.add_row("PM indicator brightness", str(config.pm_indicator_brightness))
    prefs.add_row("Capacitive control", _bool(config.capacitive_ctrl))
    prefs.add_row("Magic touch control", _bool(config.magic_touch_ctrl))
    prefs.add_row("AQI color RGB", _bool(config.aqi_color_rgb_feature))
    prefs.add_row("Motion away", _bool(config.motion_away_feature))
    prefs.add_row("Adaptive nightlight", _bool(config.adaptive_nightlight_feature))
    prefs.add_row(
        "Adaptive brightness",
        f"{config.adaptive_min_brightness}–{config.adaptive_max_brightness}",
    )
    prefs.add_row("Occupancy nightlight", _bool(config.occupancy_nightlight_feature))
    console.print(prefs)

    if config.home_away_enabled is not None:
        home = _kv_table("Home/Away simulation")
        home.add_row("Enabled", _bool(config.home_away_enabled))
        home.add_row("Outlet 1", _bool(config.home_away_outlet1_enabled))
        home.add_row("Outlet 2", _bool(config.home_away_outlet2_enabled))
        home.add_row("Nightlight", _bool(config.home_away_nightlight_enabled))
        console.print(home)

    if config.mqtt_enabled is not None:
        mqtt = _kv_table("MQTT")
        mqtt.add_row("Enabled", _bool(config.mqtt_enabled))
        mqtt.add_row("Broker", config.mqtt_broker_url or "—")
        mqtt.add_row("User", config.mqtt_user or "—")
        mqtt.add_row("QoS", str(config.mqtt_qos))
        console.print(mqtt)

    if config.internet_ip is not None:
        net = _kv_table("Network")
        net.add_row("IP", _text(config.internet_ip))
        net.add_row("Main DNS", _text(config.internet_main_dns))
        net.add_row("Backup DNS", _text(config.internet_backup_dns))
        console.print(net)


def render_status(status: OutletStatus) -> None:
    """Render the on/off state of each outlet."""
    table = Table(title="Outlets", title_justify="left", box=box.SIMPLE)
    table.add_column("Outlet", style="cyan")
    table.add_column("State")
    for index, on in enumerate(status.outlets, start=1):
        table.add_row(str(index), "[green]on[/green]" if on else "[dim]off[/dim]")
    console.print(table)


def render_names(names: Iterable[AccessoryName]) -> None:
    """Render the accessory-name mapping."""
    table = Table(title="Accessory names", title_justify="left", box=box.SIMPLE)
    table.add_column("Accessory", style="cyan", justify="right")
    table.add_column("Name")
    for name in names:
        table.add_row(str(name.accessory), name.name)
    console.print(table)


def render_nightlight(state: NightlightState) -> None:
    """Render the current nightlight state."""
    table = _kv_table("Nightlight")
    table.add_row("On", _bool(state.on))
    table.add_row("Mode", str(state.mode))
    table.add_row("Brightness", str(state.brightness))
    console.print(table)


def render_color(state: ColorLightState) -> None:
    """Render a color light's per-LED state."""
    table = Table(
        title=f"Color light {state.light} (mode {state.mode})",
        title_justify="left",
        box=box.SIMPLE,
    )
    table.add_column("LED", style="cyan", justify="right")
    table.add_column("On")
    table.add_column("Brightness", justify="right")
    table.add_column("Hue", justify="right")
    table.add_column("Sat", justify="right")
    table.add_column("Temp", justify="right")
    for index, led in enumerate(state.leds):
        table.add_row(
            str(index),
            _bool(led.state),
            str(led.brightness),
            str(led.hue),
            str(led.saturation),
            f"{led.temperature}K",
        )
    console.print(table)


def render_updates(updates: AvailableUpdates) -> None:
    """Render available firmware updates."""
    table = Table(title="Firmware", title_justify="left", box=box.SIMPLE)
    table.add_column("Module", style="cyan")
    table.add_column("Installed")
    table.add_column("Available")
    table.add_row("InvisOutlet", updates.im.fw_rev or "—", updates.im.available_fw_rev or "—")
    if updates.pm:
        table.add_row("InvisDeco", updates.pm.fw_rev or "—", updates.pm.available_fw_rev or "—")
    console.print(table)
    available = updates.update_available
    console.print(
        f"Update available: {'[yellow]yes[/yellow]' if available else '[green]no[/green]'}"
    )


def render_discovered(devices: list[DiscoveredDevice]) -> None:
    """Render devices found via mDNS discovery."""
    if not devices:
        console.print("[yellow]No devices found.[/yellow]")
        return
    table = Table(title="Discovered devices", title_justify="left", box=box.SIMPLE)
    table.add_column("Name", style="cyan")
    table.add_column("Host")
    table.add_column("Serial")
    table.add_column("Type")
    for device in devices:
        table.add_row(
            device.name,
            f"{device.host}:{device.port}",
            device.serial_number,
            device.device_type or "—",
        )
    console.print(table)


def sensor_table(info: DeviceInfo, data: SensorData, us: bool) -> Table:
    """Build a sensor-reading table for the live ``watch`` display."""
    table = Table(
        title=f"{info.device} ({info.serial_number})",
        title_justify="left",
        box=box.ROUNDED,
        show_header=False,
    )
    table.add_column("Reading", style="cyan", no_wrap=True)
    table.add_column("Value", justify="right")
    table.add_row("Temperature", fmt_temperature(data.temperature, us))
    table.add_row("Humidity", "—" if data.humidity is None else f"{data.humidity:.0f} %")
    table.add_row("AQI", "—" if data.air_quality_index is None else str(data.air_quality_index))
    table.add_row("CO₂", "—" if data.co2 is None else f"{data.co2} ppm")
    table.add_row("VOC", "—" if data.voc is None else f"{data.voc} ppm")
    table.add_row("Pressure", fmt_pressure(data.pressure, us))
    table.add_row("Illuminance", "—" if data.illuminance is None else f"{data.illuminance:.0f} lx")
    table.add_row("Distance", fmt_distance(data.distance, us))
    table.add_row("Occupancy", _bool(data.occupancy))
    table.add_row("Motion", _bool(data.motion))
    return table
