"""Tests for the Typer-based ``intecular`` CLI.

The client is replaced by a recording fake (an async context manager returning
canned models) so these tests cover argument parsing, command wiring and
rendering without any network access.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from intecular_client import (
    AccessoryName,
    AvailableUpdates,
    ColorLightState,
    DeviceConfig,
    DeviceInfo,
    DiscoveredDevice,
    FirmwareUpdate,
    NightlightState,
    OutletStatus,
)
from intecular_client.cli import config, picker, state
from intecular_client.cli.app import app
from intecular_client.cli.commands import default as default_module
from intecular_client.cli.formatters import (
    fmt_distance,
    fmt_pressure,
    fmt_temperature,
)
from intecular_client.models import OtaResult

runner = CliRunner()


class RecordingClient:
    """Async-context fake that records calls and returns canned models."""

    def __init__(self, host: str, port: int = 80) -> None:
        """Store the host and the shared call log, recording the connection."""
        self.host = host
        self.calls: list[tuple[str, tuple[Any, ...]]] = _CALLS
        self.calls.append(("connect", (host,)))
        self._ota_result: Any = None

    async def __aenter__(self) -> "RecordingClient":
        """Enter the async context."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the async context."""

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))

    # --- read methods -------------------------------------------------
    async def get_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            serial_number="SN12345",
            mac="AA:BB:CC:DD:EE:FF",
            device="InvisOutlet",
            hw_rev="1.0",
            fw_rev="2.3",
            host="10.0.0.5",
            port=80,
        )

    async def get_config(self) -> DeviceConfig:
        return DeviceConfig(pm_indicator_brightness=60, capacitive_ctrl=True)

    async def get_outlet_status(self) -> OutletStatus:
        return OutletStatus(outlets=[True, False])

    async def get_accessory_names(self) -> list[AccessoryName]:
        return [AccessoryName(accessory=1, name="Lamp")]

    async def get_nightlight(self) -> NightlightState:
        return NightlightState(mode=1, brightness=42)

    async def get_nightlight_color(self) -> ColorLightState:
        return ColorLightState(light=5, mode=2, leds=[])

    async def get_available_updates(self) -> AvailableUpdates:
        return AvailableUpdates(im=FirmwareUpdate(fw_rev="2.3", available_fw_rev="2.3"))

    # --- control methods (recorded) -----------------------------------
    async def set_outlet(self, outlet: int, on: bool) -> None:
        self._record("set_outlet", outlet, on)

    async def set_accessory_names(self, names: list[AccessoryName]) -> None:
        self._record("set_accessory_names", names)

    async def set_nightlight(self, mode: int, brightness: int) -> None:
        self._record("set_nightlight", mode, brightness)

    async def set_nightlight_temperature(
        self, kelvin: int, brightness: int = 100, on: bool = True
    ) -> None:
        self._record("set_nightlight_temperature", kelvin, brightness, on)

    async def set_nightlight_color(
        self, hue: int, saturation: int, brightness: int = 100, on: bool = True
    ) -> None:
        self._record("set_nightlight_color", hue, saturation, brightness, on)

    async def restart(self) -> None:
        self._record("restart")

    async def reset_network(self) -> None:
        self._record("reset_network")

    async def factory_reset(self) -> None:
        self._record("factory_reset")

    async def restart_invisdeco(self) -> None:
        self._record("restart_invisdeco")

    async def reset_invisdeco(self) -> None:
        self._record("reset_invisdeco")

    async def calibrate_occupancy(self, seconds: int) -> None:
        self._record("calibrate_occupancy", seconds)

    async def calibrate_temp_humidity(self, temperature: float, humidity: float) -> None:
        self._record("calibrate_temp_humidity", temperature, humidity)

    # --- OTA: invoke the result callback so the command doesn't block --
    def on_ota_progress(self, callback: Any) -> Any:
        return lambda: None

    def on_ota_result(self, callback: Any) -> Any:
        self._ota_result = callback
        return lambda: None

    async def perform_ota_update(self, target: int, method: int) -> None:
        self._record("perform_ota_update", target, method)
        if self._ota_result is not None:
            self._ota_result(OtaResult(device=target, status=1))


_CALLS: list[tuple[str, tuple[Any, ...]]] = []


@pytest.fixture(autouse=True)
def fake_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> list[tuple[str, tuple[Any, ...]]]:
    """Isolate config to a tmp file, fake the client, and reset the call log.

    A default device is pre-seeded so commands resolve a host without invoking
    the discovery picker; tests that exercise the picker clear it first.
    """
    _CALLS.clear()
    monkeypatch.setenv("INTECULAR_CLI_CONFIG", str(tmp_path / "cli.json"))
    monkeypatch.setattr(state, "IntecularClient", RecordingClient)
    monkeypatch.setattr(default_module, "IntecularClient", RecordingClient)
    config.set_default_device(
        config.DefaultDevice(host="10.0.0.99", name="Default", serial_number="SN-DEF")
    )
    return _CALLS


# --- help -----------------------------------------------------------------


def test_help_lists_groups() -> None:
    """The top-level help lists the noun groups and flat commands."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for group in ("default", "device", "nightlight", "indicator", "outlet", "name"):
        assert group in result.output
    assert "Stream live sensor data" in result.output


def test_command_help_shows_arguments() -> None:
    """Per-command help documents its arguments (the original complaint)."""
    result = runner.invoke(app, ["nightlight", "aura", "color", "--help"])
    assert result.exit_code == 0
    assert "HUE" in result.output
    assert "--off" in result.output


# --- read / render --------------------------------------------------------


def test_info_renders_values() -> None:
    """`device info` renders fields from the fake device."""
    result = runner.invoke(app, ["device", "info"])
    assert result.exit_code == 0
    assert "SN12345" in result.output
    assert "InvisOutlet" in result.output


def test_outlet_status_renders() -> None:
    """`outlet status` shows per-outlet on/off state."""
    result = runner.invoke(app, ["outlet", "status"])
    assert result.exit_code == 0
    assert "on" in result.output
    assert "off" in result.output


def test_name_list_renders() -> None:
    """`name list` renders the accessory mapping."""
    result = runner.invoke(app, ["name", "list"])
    assert result.exit_code == 0
    assert "Lamp" in result.output


def test_render_config_tolerates_int_network_fields() -> None:
    """render_config must not crash when network fields arrive as ints (Rich needs str)."""
    from intecular_client.cli import render

    cfg = DeviceConfig(internet_ip=168430081, internet_main_dns=134744072)
    render.render_config(cfg)  # must not raise NotRenderableError


# --- control wiring -------------------------------------------------------


def test_outlet_on_calls_set_outlet(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """`outlet on 2` turns outlet 2 on."""
    result = runner.invoke(app, ["outlet", "on", "2"])
    assert result.exit_code == 0
    assert ("set_outlet", (2, True)) in fake_client


def test_outlet_choice_is_validated() -> None:
    """`outlet on 3` is rejected — outlets are limited to 1 and 2."""
    result = runner.invoke(app, ["outlet", "on", "3"])
    assert result.exit_code != 0


def test_nightlight_brightness_calls_set(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """`nightlight pro brightness 75` turns it on at 75%."""
    result = runner.invoke(app, ["nightlight", "pro", "brightness", "75"])
    assert result.exit_code == 0
    assert ("set_nightlight", (1, 75)) in fake_client


def test_nightlight_temp_sets_temperature(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """`nightlight aura temp 3500` sets the nightlight white temperature."""
    result = runner.invoke(app, ["nightlight", "aura", "temp", "3500", "--bri", "90"])
    assert result.exit_code == 0
    assert ("set_nightlight_temperature", (3500, 90, True)) in fake_client


def test_nightlight_color_sets_hsv(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """`nightlight aura color 200 90` sets the nightlight color via HSV."""
    result = runner.invoke(app, ["nightlight", "aura", "color", "200", "90"])
    assert result.exit_code == 0
    assert ("set_nightlight_color", (200, 90, 100, True)) in fake_client


def test_name_set_calls_client(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """`name set 1 Lamp` writes the accessory names."""
    result = runner.invoke(app, ["name", "set", "1", "Lamp"])
    assert result.exit_code == 0
    assert any(c[0] == "set_accessory_names" for c in fake_client)


def test_deco_restart(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """`deco restart` restarts the InvisDeco."""
    result = runner.invoke(app, ["deco", "restart"])
    assert result.exit_code == 0
    assert ("restart_invisdeco", ()) in fake_client


def test_device_error_reported_cleanly(
    fake_client: list[tuple[str, tuple[Any, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A device-level error prints a message and exits, not a traceback."""
    from intecular_client import IntecularCommandError

    async def boom(self: Any) -> None:
        raise IntecularCommandError(
            "No color light at index 5; this device may not have an Aura."
        )

    monkeypatch.setattr(RecordingClient, "get_nightlight_color", boom)
    result = runner.invoke(app, ["nightlight", "aura", "status"])
    assert result.exit_code != 0
    assert "Aura" in result.output
    assert "Traceback" not in result.output


# --- device group ---------------------------------------------------------


def test_firmware_check_renders(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """`device firmware check` reads available updates."""
    result = runner.invoke(app, ["device", "firmware", "check"])
    assert result.exit_code == 0
    assert "InvisOutlet" in result.output


def test_firmware_update_performs_ota(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """`device firmware update 1` starts an OTA and completes via the result."""
    result = runner.invoke(app, ["device", "firmware", "update", "1"])
    assert result.exit_code == 0
    assert ("perform_ota_update", (1, 0)) in fake_client


def test_calibrate_climate(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """`deco calibrate climate 21 50` forwards the reference values."""
    result = runner.invoke(app, ["deco", "calibrate", "climate", "21", "50"])
    assert result.exit_code == 0
    assert ("calibrate_temp_humidity", (21.0, 50.0)) in fake_client


def test_factory_reset_aborts_without_yes(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """Declining the confirmation aborts without touching the device."""
    result = runner.invoke(app, ["device", "reset", "factory"], input="n\n")
    assert result.exit_code != 0
    assert ("factory_reset", ()) not in fake_client


def test_factory_reset_proceeds_with_yes(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """`--yes` skips the prompt and performs the reset."""
    result = runner.invoke(app, ["--yes", "device", "reset", "factory"])
    assert result.exit_code == 0
    assert ("factory_reset", ()) in fake_client


def test_version() -> None:
    """`--version` prints a version string and exits cleanly."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip()


# --- formatters -----------------------------------------------------------


@pytest.mark.parametrize(
    ("celsius", "us", "expected"),
    [(22.06, False, "22.1 °C"), (22.06, True, "71.7 °F"), (None, True, "—")],
)
def test_fmt_temperature(celsius: float | None, us: bool, expected: str) -> None:
    """Temperature formatting converts to Fahrenheit only for US units."""
    assert fmt_temperature(celsius, us) == expected


def test_fmt_pressure_and_distance() -> None:
    """Pressure and distance convert to US units when requested."""
    assert fmt_pressure(100782, True) == "29.76 inHg"
    assert fmt_pressure(100782, False) == "100782 Pa"
    assert fmt_distance(217, True) == "8.5 in"
    assert fmt_distance(217, False) == "217 mm"


# --- default-device management --------------------------------------------


def _patch_discover(monkeypatch: pytest.MonkeyPatch, devices: list[DiscoveredDevice]) -> None:
    """Replace mDNS discovery with a canned device list."""

    async def fake_discover(timeout: float = 5.0) -> list[DiscoveredDevice]:
        return devices

    monkeypatch.setattr(picker, "discover", fake_discover)


def test_default_show_no_default() -> None:
    """`default show` reports when nothing is saved."""
    config.clear_default_device()
    result = runner.invoke(app, ["default", "show"])
    assert result.exit_code == 0
    assert "No default device" in result.output


def test_default_select_host_persists() -> None:
    """`default select --host` probes and saves the device."""
    result = runner.invoke(app, ["default", "select", "--host", "10.0.0.9"])
    assert result.exit_code == 0
    saved = config.get_default_device()
    assert saved is not None
    assert saved.host == "10.0.0.9"
    assert saved.serial_number == "SN12345"


def test_default_forget_clears() -> None:
    """`default forget` removes the saved default."""
    result = runner.invoke(app, ["default", "forget"])
    assert result.exit_code == 0
    assert config.get_default_device() is None


# --- host resolution ------------------------------------------------------


def test_explicit_host_overrides_default(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """An explicit --host wins over the saved default."""
    result = runner.invoke(app, ["--host", "1.2.3.4", "device", "info"])
    assert result.exit_code == 0
    assert ("connect", ("1.2.3.4",)) in fake_client
    assert ("connect", ("10.0.0.99",)) not in fake_client


def test_saved_default_used(
    fake_client: list[tuple[str, tuple[Any, ...]]],
) -> None:
    """With no --host, commands connect to the saved default."""
    result = runner.invoke(app, ["device", "info"])
    assert result.exit_code == 0
    assert ("connect", ("10.0.0.99",)) in fake_client


def test_non_interactive_without_device_errors(
    fake_client: list[tuple[str, tuple[Any, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No host, no default, no TTY → error without ever connecting.

    CliRunner is inherently non-interactive, so this is the default state.
    """
    config.clear_default_device()
    _patch_discover(monkeypatch, [])  # guard: must error before any scan
    result = runner.invoke(app, ["device", "info"])
    assert result.exit_code != 0
    assert not any(call[0] == "connect" for call in fake_client)


def test_picker_single_device_auto_used(
    fake_client: list[tuple[str, tuple[Any, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a TTY with one device found, it is used (and offered as default)."""
    config.clear_default_device()
    _patch_discover(
        monkeypatch,
        [DiscoveredDevice("Office", "10.0.0.7", 80, "SNX", "InvisOutlet")],
    )
    monkeypatch.setattr(picker, "_is_interactive", lambda: True)
    # The only prompt is "Set as default?"; an empty line accepts the default (yes).
    result = runner.invoke(app, ["device", "info"], input="\n")
    assert result.exit_code == 0
    assert ("connect", ("10.0.0.7",)) in fake_client
    saved = config.get_default_device()
    assert saved is not None and saved.host == "10.0.0.7"


def test_picker_interactive_uses_questionary(
    fake_client: list[tuple[str, tuple[Any, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a TTY the arrow-key menu (questionary) drives the selection.

    CliRunner has no pty, so the interactive flag and questionary are mocked;
    this verifies the routing and that the chosen device is used.
    """
    config.clear_default_device()
    devices = [
        DiscoveredDevice("A", "10.0.0.1", 80, "SN1", "InvisOutlet"),
        DiscoveredDevice("B", "10.0.0.2", 80, "SN2", "InvisOutlet"),
    ]
    _patch_discover(monkeypatch, devices)
    monkeypatch.setattr(picker, "_is_interactive", lambda: True)

    class _FakeSelect:
        async def ask_async(self) -> DiscoveredDevice:
            return devices[1]

    monkeypatch.setattr(picker.questionary, "select", lambda *a, **k: _FakeSelect())

    result = runner.invoke(app, ["device", "info"], input="\n")
    assert result.exit_code == 0
    assert ("connect", ("10.0.0.2",)) in fake_client


def test_picker_interactive_no_devices_returns_none(
    fake_client: list[tuple[str, tuple[Any, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a TTY with nothing discovered → non-zero exit, no connection."""
    config.clear_default_device()
    _patch_discover(monkeypatch, [])
    monkeypatch.setattr(picker, "_is_interactive", lambda: True)
    result = runner.invoke(app, ["device", "info"])
    assert result.exit_code != 0
    assert not any(call[0] == "connect" for call in fake_client)
