"""Tests for the Rich render helpers.

Each helper prints to the module-level ``render.console``; we capture that
output and assert on the plain text so a refactor of the table layout is caught
by a content change rather than passing silently.
"""

from __future__ import annotations

from invisoutlet.cli import render
from invisoutlet.discovery import DiscoveredDevice
from invisoutlet.models import (
    AccessoryName,
    AvailableUpdates,
    ColorLedEntry,
    ColorLightState,
    DeviceConfig,
    DeviceInfo,
    FirmwareUpdate,
    NightlightState,
    OutletStatus,
    SensorData,
    SubDeviceInfo,
)


def capture(fn, *args: object) -> str:
    """Run a render helper and return its console output as plain text."""
    with render.console.capture() as cap:
        fn(*args)
    return cap.get()


# --- primitive helpers ----------------------------------------------------


def test_bool_renders_three_states() -> None:
    """_bool maps None/True/False to em-dash/yes/no."""
    assert "—" in render._bool(None)
    assert "yes" in render._bool(True)
    assert "no" in render._bool(False)


def test_text_renders_blank_and_value() -> None:
    """_text shows an em-dash for None or empty string, else str()."""
    assert render._text(None) == "—"
    assert render._text("") == "—"
    assert render._text(0) == "0"
    assert render._text(42) == "42"


# --- render_info ----------------------------------------------------------


def test_render_info_without_sub_device() -> None:
    """A bare device prints its fields and an em-dash for missing revs."""
    info = DeviceInfo(serial_number="SN1", mac="aa:bb", device="InvisOutlet", host="10.0.0.9")
    out = capture(render.render_info, info)
    assert "SN1" in out
    assert "aa:bb" in out
    assert "10.0.0.9:3333" in out
    assert "Sub-device" not in out


def test_render_info_with_sub_device_and_radar() -> None:
    """A sub-device with radar prints the sub table and radar row."""
    info = DeviceInfo(
        serial_number="SN1",
        mac="aa",
        device="InvisOutlet",
        hw_rev="1.0",
        fw_rev="2.0",
        sub_device=SubDeviceInfo(
            serial_number="PM9",
            mac="cc",
            device="InvisDeco",
            device_type="deco",
            online=True,
            radar_fw_ver="3.0",
            radar_hw_type="R1",
        ),
    )
    out = capture(render.render_info, info)
    assert "Sub-device" in out
    assert "PM9" in out
    assert "R1 fw 3.0" in out


def test_render_info_sub_device_without_radar() -> None:
    """A sub-device lacking radar firmware omits the radar row."""
    info = DeviceInfo(
        serial_number="SN1",
        mac="aa",
        device="InvisOutlet",
        sub_device=SubDeviceInfo(serial_number="PM9", mac="cc", device="InvisDeco"),
    )
    out = capture(render.render_info, info)
    assert "Sub-device" in out
    assert "PM9" in out
    assert "R1" not in out  # no radar row


# --- render_config --------------------------------------------------------


def test_render_config_prefs_only() -> None:
    """With only accessory prefs set, the optional sections are omitted."""
    cfg = DeviceConfig(
        outlet_power_indicator_on=True,
        pm_indicator_brightness=50,
        adaptive_min_brightness=5,
        adaptive_max_brightness=80,
    )
    out = capture(render.render_config, cfg)
    assert "Accessory preferences" in out
    assert "5–80" in out
    assert "Home/Away simulation" not in out
    assert "MQTT" not in out
    assert "Network" not in out


def test_render_config_all_sections() -> None:
    """Setting the gating fields turns on every optional section."""
    cfg = DeviceConfig(
        home_away_enabled=True,
        home_away_outlet1_enabled=False,
        mqtt_enabled=True,
        mqtt_broker_url="mqtt://b",
        mqtt_user="u",
        mqtt_qos=1,
        internet_ip="10.0.0.5",
        internet_main_dns="1.1.1.1",
    )
    out = capture(render.render_config, cfg)
    assert "Home/Away simulation" in out
    assert "MQTT" in out
    assert "mqtt://b" in out
    assert "Network" in out
    assert "10.0.0.5" in out


def test_render_config_tolerates_int_network_fields() -> None:
    """Network fields arriving as ints must render (Rich needs a str)."""
    cfg = DeviceConfig(internet_ip=168430081, internet_main_dns=134744072)  # type: ignore[arg-type]
    out = capture(render.render_config, cfg)
    assert "168430081" in out


# --- render_status / names / nightlight -----------------------------------


def test_render_status_shows_on_and_off() -> None:
    """Each outlet renders its 1-based index and on/off state."""
    out = capture(render.render_status, OutletStatus(outlets=[True, False]))
    assert "on" in out
    assert "off" in out
    assert "1" in out
    assert "2" in out


def test_render_names() -> None:
    """Accessory names render with their accessory id."""
    out = capture(render.render_names, [AccessoryName(accessory=1, name="Lamp")])
    assert "Lamp" in out
    assert "1" in out


def test_render_nightlight() -> None:
    """Nightlight renders on-state, mode and brightness."""
    out = capture(render.render_nightlight, NightlightState(mode=2, brightness=75))
    assert "yes" in out
    assert "2" in out
    assert "75" in out


# --- render_color ---------------------------------------------------------


def test_render_color() -> None:
    """Each LED renders index, on-state and its numeric fields."""
    state = ColorLightState(
        light=5,
        mode=2,
        leds=[
            ColorLedEntry(state=True, brightness=100, hue=200, saturation=60, temperature=4000),
            ColorLedEntry(state=False, brightness=0, hue=0, saturation=0, temperature=3000),
        ],
    )
    out = capture(render.render_color, state)
    assert "Color light 5 (mode 2)" in out
    assert "4000K" in out
    assert "200" in out


# --- render_updates -------------------------------------------------------


def test_render_updates_with_pm_and_available() -> None:
    """A PM module and a newer rev report the InvisDeco row and 'yes'."""
    updates = AvailableUpdates(
        im=FirmwareUpdate(fw_rev="1.0", available_fw_rev="1.1"),
        pm=FirmwareUpdate(fw_rev="2.0", available_fw_rev="2.0"),
    )
    out = capture(render.render_updates, updates)
    assert "InvisDeco" in out
    assert "Update available: yes" in out


def test_render_updates_without_pm_and_up_to_date() -> None:
    """No PM and matching revs omits the InvisDeco row and reports 'no'."""
    updates = AvailableUpdates(im=FirmwareUpdate(fw_rev="1.0", available_fw_rev="1.0"))
    out = capture(render.render_updates, updates)
    assert "InvisDeco" not in out
    assert "Update available: no" in out


# --- render_discovered ----------------------------------------------------


def test_render_discovered_empty() -> None:
    """An empty list prints the no-devices notice and no table."""
    out = capture(render.render_discovered, [])
    assert "No devices found" in out
    assert "Discovered devices" not in out


def test_render_discovered_lists_devices() -> None:
    """Devices render host:port and an em-dash for a missing type."""
    devices = [
        DiscoveredDevice(
            name="Kitchen", host="10.0.0.5", port=3333, serial_number="SN1", device_type="outlet"
        ),
        DiscoveredDevice(
            name="Hall", host="10.0.0.6", port=3333, serial_number="SN2", device_type=""
        ),
    ]
    out = capture(render.render_discovered, devices)
    assert "Kitchen" in out
    assert "10.0.0.5:3333" in out
    assert "—" in out  # empty device_type for the second row


# --- sensor_table ---------------------------------------------------------


def _info() -> DeviceInfo:
    return DeviceInfo(serial_number="SN1", mac="aa", device="InvisOutlet")


def test_sensor_table_metric_with_values() -> None:
    """Metric units render every populated reading."""
    data = SensorData(
        temperature=21.5,
        humidity=40.0,
        air_quality_index=75,
        co2=600,
        voc=0.5,
        pressure=101325,
        illuminance=120.0,
        distance=150,
        occupancy_state=1,
        movement_energy=10,
    )
    table = render.sensor_table(_info(), data, us=False)
    out = capture(render.console.print, table)
    assert "21.5 °C" in out
    assert "40 %" in out
    assert "101325 Pa" in out
    assert "150 mm" in out
    assert "yes" in out  # occupancy / motion


def test_sensor_table_us_units() -> None:
    """US units convert temperature, pressure and distance."""
    data = SensorData(temperature=0.0, pressure=101325, distance=254)
    table = render.sensor_table(_info(), data, us=True)
    out = capture(render.console.print, table)
    assert "°F" in out
    assert "inHg" in out
    assert "in" in out


def test_sensor_table_missing_values_render_dash() -> None:
    """Absent readings fall back to an em-dash rather than raising."""
    table = render.sensor_table(_info(), SensorData(), us=False)
    out = capture(render.console.print, table)
    assert "—" in out
