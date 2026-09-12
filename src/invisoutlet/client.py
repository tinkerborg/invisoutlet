"""Client for communicating with InvisOutlet devices over WebSocket."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from enum import IntEnum
from functools import partial
import json
import logging
import random
from typing import Any, TypeVar

import aiohttp

from .exceptions import (
    InvisOutletCommandError,
    InvisOutletConnectionError,
    InvisOutletError,
    InvisOutletTimeoutError,
)
from .models import (
    AccessoryName,
    AvailableUpdates,
    ColorLedEntry,
    ColorLightState,
    DeviceConfig,
    DeviceInfo,
    FirmwareRelease,
    NightlightState,
    OtaProgress,
    OtaResult,
    OutletStatus,
    SensorData,
)

_LOGGER = logging.getLogger(__name__)

# Documented WebSocket callback names.
CALLBACK_CONFIG_GET = 1
CALLBACK_CONFIG_SET = 2
CALLBACK_ACCESSORY_NAMES_GET = 3
CALLBACK_ACCESSORY_NAMES_SET = 4
CALLBACK_RESTART = 5
CALLBACK_RESET_NETWORK = 6
CALLBACK_FACTORY_RESET = 7
CALLBACK_OUTLET_STATUS = 9
CALLBACK_OUTLET_SET = 10
CALLBACK_SENSOR_DATA = 11
CALLBACK_DEVICE_INFO = 12
CALLBACK_NIGHTLIGHT_SET = 14
CALLBACK_NIGHTLIGHT_STATUS = 15
CALLBACK_COLOR_LIGHT_TEMPERATURE = 17
CALLBACK_COLOR_LIGHT = 18
CALLBACK_UPDATES_GET = 20
CALLBACK_OTA_PERFORM = 21
CALLBACK_OTA_PROGRESS = 22
CALLBACK_OTA_RESULT = 23
CALLBACK_RESTART_INVISDECO = 24
CALLBACK_RESET_INVISDECO = 25
CALLBACK_OCCUPANCY_CALIBRATION = 26
CALLBACK_TEMP_HUMIDITY_CALIBRATION = 28


class OtaTarget(IntEnum):
    """Which device an OTA firmware update targets (callback 21).

    Values match the device's 1-based numbering, shared with the ``device_type``
    in the progress/result pushes (callbacks 22/23).
    """

    INVISOUTLET = 1
    INVISDECO = 2


def target_for_device_type(device_type: int) -> OtaTarget | None:
    """Map an OTA push ``device_type`` to the :class:`OtaTarget` it belongs to.

    The pushes (callbacks 22/23) are 1-based: 1 = InvisOutlet, 2 = InvisDeco,
    3 = the outlet's WWW partition (part of the outlet's own update). Returns
    ``None`` for an unrecognized value.
    """
    if device_type in (1, 3):
        return OtaTarget.INVISOUTLET
    if device_type == 2:
        return OtaTarget.INVISDECO
    return None


# device_type 3 (the outlet's WWW partition) reports as its own progress/result
# stream but is a sub-phase of the outlet update, which ends with device_type 1.
# A *successful* WWW result therefore isn't terminal — the main phase follows.
_OTA_SUBPHASE_DEVICE_TYPE = 3


# Seconds without a progress push before an in-flight OTA update is treated as
# failed. The device emits a junk status-0 result at the start of every update
# (indistinguishable from a real early failure), so a stall timer is the only
# reliable way to detect a genuine pre-download failure.
_OTA_STALL_TIMEOUT = 60.0


# InvisOutlet firmware-update (OTA) check service. Queried per module over HTTP to
# learn the latest revision, its download URL and the release notes. The path is
# ``/<module>/<product>/<hw_rev>/<current_fw>``.
_OTA_CHECK_BASE = "https://oxv6el7gq2dyr57ljslfu5osrq0nhohh.lambda-url.us-east-1.on.aws"
_OTA_MODULE = {OtaTarget.INVISOUTLET: "IM", OtaTarget.INVISDECO: "PM"}
# Device model (or faceplate variant) -> product code in the OTA-check URL. The
# codes aren't reported by the device, so anything absent here has no known update
# channel and :meth:`InvisOutletClient.check_firmware` returns ``None``. Faceplates
# share the model name "InvisDeco", so the color Aura is keyed by its variant.
_OTA_PRODUCT_CODES = {"InvisOutlet": "IVO1", "InvisDeco": "PRP1", "Aura": "LIP1"}


# Light-array selector (the first ``callbackArgs`` element of callbacks 17/18):
# the nightlight (9 LEDs).
LIGHT_NIGHTLIGHT = 5

# Color-temperature range the color arrays accept, in kelvin.
MIN_KELVIN = 1000
MAX_KELVIN = 6500


class ColorEffect(IntEnum):
    """Animated effect modes for a color array (callback 17, arg 2).

    Modes 1 (static HSV) and 2 (static temperature) are set via the
    ``set_color_*`` helpers; these are the self-animating modes.
    """

    BREATHING = 3
    STROBING = 4
    COLOR_CYCLE = 5
    RAINBOW = 6
    STARRY_NIGHT = 7


# Auto-reconnect backoff bounds (seconds).
_RECONNECT_INITIAL_DELAY = 1.0
_RECONNECT_MAX_DELAY = 60.0

# WebSocket ping interval (seconds). Lets aiohttp detect a silently-dropped
# connection (e.g. the device rebooting) instead of waiting forever for data.
# This is also the detection latency, so keep it fairly low.
_WS_HEARTBEAT = 10.0


_CB = TypeVar("_CB", bound=Callable[..., None])


def _add_to(callbacks: list[_CB], callback: _CB) -> Callable[[], None]:
    """Append a callback to a list and return an unsubscribe function."""
    callbacks.append(callback)

    def _remove() -> None:
        if callback in callbacks:
            callbacks.remove(callback)

    return _remove


def _fire(callbacks: list[Callable[..., None]], name: str, *args: object) -> None:
    """Invoke each callback with ``args``, logging and swallowing errors."""
    for callback in list(callbacks):
        try:
            callback(*args)
        except Exception:
            _LOGGER.exception("Error in %s callback", name)


class InvisOutletClient:
    """Client for InvisOutlet smart outlet devices over WebSocket."""

    def __init__(self, host: str, port: int = 80) -> None:
        """Initialize the client."""
        self.host = host
        self.port = port
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._listeners: dict[int, list[Callable[[dict[str, Any]], None]]] = {}
        self._pending_requests: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._read_task: asyncio.Task[None] | None = None
        self._closing = False
        self._connect_callbacks: list[Callable[[], None]] = []
        self._disconnect_callbacks: list[Callable[[], None]] = []
        # OTA state: per-target stall timer, which targets have reported progress
        # since their trigger, and the gated result subscribers.
        self._ota_stall: dict[OtaTarget, asyncio.TimerHandle] = {}
        self._ota_seen_progress: set[OtaTarget] = set()
        self._ota_result_callbacks: list[Callable[[OtaResult], None]] = []
        # Internal listeners that drive the stall timer and gate result pushes.
        self._add_listener(CALLBACK_OTA_PROGRESS, self._on_raw_ota_progress)
        self._add_listener(CALLBACK_OTA_RESULT, self._on_raw_ota_result)

    async def connect(self) -> None:
        """Connect to the device and keep the connection alive.

        Raises on the *initial* connection failure. Once connected, a background
        task reads messages and automatically reconnects with backoff if the
        connection drops, until :meth:`close` is called. Registered listeners
        survive reconnects, so pushes resume automatically.
        """
        self._closing = False
        try:
            await self._connect_ws()
        except InvisOutletError:
            await self._cleanup_session()
            raise
        self._read_task = asyncio.create_task(self._supervise())

    async def close(self) -> None:
        """Close the connection and stop reconnecting."""
        self._closing = True
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        await self._cleanup_session()

        # Cancel any pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

        # Cancel any in-flight OTA stall timers
        for handle in self._ota_stall.values():
            handle.cancel()
        self._ota_stall.clear()
        self._ota_seen_progress.clear()

    async def _connect_ws(self) -> None:
        """Open the WebSocket (creating the session if needed). Raises on failure."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        try:
            self._ws = await asyncio.wait_for(
                self._session.ws_connect(
                    f"ws://{self.host}:{self.port}/ws", heartbeat=_WS_HEARTBEAT
                ),
                timeout=10.0,
            )
        except TimeoutError as err:
            raise InvisOutletTimeoutError(
                f"Timeout connecting to {self.host}:{self.port}"
            ) from err
        except (OSError, aiohttp.ClientError) as err:
            raise InvisOutletConnectionError(
                f"Cannot connect to {self.host}:{self.port}: {err}"
            ) from err
        self._notify_connected()

    def on_connect(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback invoked after each successful (re)connect.

        Returns a function to unregister the callback.
        """
        return _add_to(self._connect_callbacks, callback)

    def on_disconnect(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback invoked when the connection is lost.

        Not fired on an intentional :meth:`close`. Returns a function to
        unregister the callback.
        """
        return _add_to(self._disconnect_callbacks, callback)

    def _notify_connected(self) -> None:
        """Fire the registered on-connect callbacks."""
        _fire(self._connect_callbacks, "on_connect")

    def _notify_disconnected(self) -> None:
        """Fire the registered on-disconnect callbacks."""
        _fire(self._disconnect_callbacks, "on_disconnect")

    async def _cleanup_session(self) -> None:
        """Close the WebSocket and HTTP session."""
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _supervise(self) -> None:
        """Read messages, reconnecting with backoff until the client is closed."""
        delay = _RECONNECT_INITIAL_DELAY
        while not self._closing:
            await self._read_loop()
            if self._closing:
                break

            await self._handle_disconnect()

            while not self._closing:
                await asyncio.sleep(delay)
                if self._closing:
                    break
                try:
                    await self._connect_ws()
                except InvisOutletError as err:
                    _LOGGER.debug("Reconnect to %s failed: %s", self.host, err)
                    delay = min(delay * 2, _RECONNECT_MAX_DELAY)
                    continue
                _LOGGER.info("Reconnected to %s", self.host)
                delay = _RECONNECT_INITIAL_DELAY
                break

    async def _handle_disconnect(self) -> None:
        """Tear down a dropped connection and fail any in-flight requests."""
        _LOGGER.warning("Connection to %s lost; reconnecting", self.host)
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(InvisOutletConnectionError("Connection lost"))
        self._pending_requests.clear()
        self._notify_disconnected()

    async def __aenter__(self) -> InvisOutletClient:
        """Enter async context manager."""
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit async context manager."""
        await self.close()

    def on_sensor_data(
        self, callback: Callable[[SensorData], None]
    ) -> Callable[[], None]:
        """Register a callback for sensor data updates.

        Returns a function to unregister the callback.
        """

        def _wrapper(msg: dict[str, Any]) -> None:
            args = msg.get("payload", {}).get("callbackArgs", [])
            if len(args) >= 2 and isinstance(args[1], dict):
                callback(SensorData.from_raw(args[1]))

        return self._add_listener(CALLBACK_SENSOR_DATA, _wrapper)

    def on_outlet_status(
        self, callback: Callable[[OutletStatus], None]
    ) -> Callable[[], None]:
        """Register a callback for pushed outlet-status updates.

        The device broadcasts callback 9 when outlet state changes (e.g. from
        another controller or the physical button). The push envelope may carry
        the status list directly or wrapped, so both shapes are accepted.

        Returns a function to unregister the callback.
        """

        def _wrapper(msg: dict[str, Any]) -> None:
            args = msg.get("payload", {}).get("callbackArgs", [])
            if not isinstance(args, list) or not args:
                return
            status = args[1] if len(args) >= 2 and isinstance(args[1], list) else args
            callback(OutletStatus.from_raw(status))

        return self._add_listener(CALLBACK_OUTLET_STATUS, _wrapper)

    def on_message(
        self, callback_name: int, callback: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Register a callback for a specific message type.

        Returns a function to unregister the callback.
        """
        return self._add_listener(callback_name, callback)

    async def set_outlet(self, outlet: int, on: bool, timeout: float = 5.0) -> None:
        """Set the state of an outlet.

        Args:
            outlet: Outlet number (1 or 2).
            on: True to turn on, False to turn off.

        """
        await self._send_request(CALLBACK_OUTLET_SET, [outlet, int(on)], timeout)

    async def get_config(self, timeout: float = 5.0) -> DeviceConfig:
        """Request device configuration."""
        response = await self._send_request(CALLBACK_CONFIG_GET, timeout=timeout)
        args = response.get("payload", {}).get("callbackArgs", {})
        return DeviceConfig.from_raw(args)

    async def get_sensor_data(self, timeout: float = 5.0) -> SensorData:
        """Fetch the faceplate's latest sensor readings on demand (callback 11).

        Returns the same payload the device streams; fields a faceplate lacks are
        omitted and come back as ``None``.
        """
        response = await self._send_request(CALLBACK_SENSOR_DATA, timeout=timeout)
        args = response.get("payload", {}).get("callbackArgs", [])
        if len(args) >= 2 and isinstance(args[1], dict):
            return SensorData.from_raw(args[1])
        return SensorData()

    async def set_config(
        self,
        *,
        outlet_power_indicator_on: bool | None = None,
        pm_indicator_brightness: int | None = None,
        capacitive_ctrl: bool | None = None,
        aqi_color_rgb_feature: bool | None = None,
        motion_away_feature: bool | None = None,
        adaptive_nightlight_feature: bool | None = None,
        adaptive_min_brightness: int | None = None,
        adaptive_max_brightness: int | None = None,
        occupancy_nightlight_feature: bool | None = None,
        override_adaptive_occupancy_nightlight_feature: bool | None = None,
        magic_touch_ctrl: bool | None = None,
        home_away_enabled: bool | None = None,
        home_away_outlet1_enabled: bool | None = None,
        home_away_outlet2_enabled: bool | None = None,
        home_away_nightlight_enabled: bool | None = None,
        home_away_min_brightness: int | None = None,
        home_away_max_brightness: int | None = None,
        home_away_min_on_duration: int | None = None,
        home_away_max_on_duration: int | None = None,
        home_away_min_off_duration: int | None = None,
        home_away_max_off_duration: int | None = None,
        mqtt_enabled: bool | None = None,
        mqtt_broker_url: str | None = None,
        mqtt_user: str | None = None,
        mqtt_password: str | None = None,
        mqtt_qos: int | None = None,
        timeout: float = 5.0,
    ) -> None:
        """Set device configuration.

        Only the fields you pass are sent; everything left as ``None`` is
        omitted from the wire payload.
        """
        config = DeviceConfig(
            outlet_power_indicator_on=outlet_power_indicator_on,
            pm_indicator_brightness=pm_indicator_brightness,
            capacitive_ctrl=capacitive_ctrl,
            aqi_color_rgb_feature=aqi_color_rgb_feature,
            motion_away_feature=motion_away_feature,
            adaptive_nightlight_feature=adaptive_nightlight_feature,
            adaptive_min_brightness=adaptive_min_brightness,
            adaptive_max_brightness=adaptive_max_brightness,
            occupancy_nightlight_feature=occupancy_nightlight_feature,
            override_adaptive_occupancy_nightlight_feature=override_adaptive_occupancy_nightlight_feature,
            magic_touch_ctrl=magic_touch_ctrl,
            home_away_enabled=home_away_enabled,
            home_away_outlet1_enabled=home_away_outlet1_enabled,
            home_away_outlet2_enabled=home_away_outlet2_enabled,
            home_away_nightlight_enabled=home_away_nightlight_enabled,
            home_away_min_brightness=home_away_min_brightness,
            home_away_max_brightness=home_away_max_brightness,
            home_away_min_on_duration=home_away_min_on_duration,
            home_away_max_on_duration=home_away_max_on_duration,
            home_away_min_off_duration=home_away_min_off_duration,
            home_away_max_off_duration=home_away_max_off_duration,
            mqtt_enabled=mqtt_enabled,
            mqtt_broker_url=mqtt_broker_url,
            mqtt_user=mqtt_user,
            mqtt_password=mqtt_password,
            mqtt_qos=mqtt_qos,
        )
        await self._send_request(CALLBACK_CONFIG_SET, [config.to_raw()], timeout)

    async def get_device_info(self, timeout: float = 5.0) -> DeviceInfo:
        """Request device information."""
        response = await self._send_request(CALLBACK_DEVICE_INFO, timeout=timeout)
        args = response.get("payload", {}).get("callbackArgs", {})
        return DeviceInfo.from_raw(args, self.host, self.port)

    async def get_accessory_names(self, timeout: float = 5.0) -> list[AccessoryName]:
        """Request the user-assigned accessory names."""
        response = await self._send_request(
            CALLBACK_ACCESSORY_NAMES_GET, timeout=timeout
        )
        args = response.get("payload", {}).get("callbackArgs", [])
        # Real firmware returns a bare list; the docs wrap it as {"payload": [...]}.
        items = args.get("payload", []) if isinstance(args, dict) else args
        return [AccessoryName.from_raw(item) for item in items]

    async def set_accessory_names(
        self, names: list[AccessoryName], timeout: float = 5.0
    ) -> None:
        """Set the user-assigned accessory names."""
        await self._send_request(
            CALLBACK_ACCESSORY_NAMES_SET,
            [name.to_raw() for name in names],
            timeout,
        )

    async def restart(self) -> None:
        """Restart the InvisOutlet. The device sends no response."""
        await self._send_command_noreply(CALLBACK_RESTART)

    async def reset_network(self) -> None:
        """Reset the InvisOutlet's network settings. Sends no response.

        The device will drop off the network after this call.
        """
        await self._send_command_noreply(CALLBACK_RESET_NETWORK)

    async def factory_reset(self) -> None:
        """Factory-reset the InvisOutlet. Sends no response.

        This erases all configuration; the device returns to setup mode.
        """
        await self._send_command_noreply(CALLBACK_FACTORY_RESET)

    async def get_outlet_status(self, timeout: float = 5.0) -> OutletStatus:
        """Fetch the on/off state of each outlet."""
        response = await self._send_request(CALLBACK_OUTLET_STATUS, timeout=timeout)
        args = response.get("payload", {}).get("callbackArgs", [])
        return OutletStatus.from_raw(args)

    async def set_nightlight(
        self, mode: int, brightness: int, timeout: float = 5.0
    ) -> None:
        """Control the nightlight.

        Args:
            mode: Nightlight mode (0 = off, >0 = on).
            brightness: Brightness 0-100.

        """
        await self._send_request(CALLBACK_NIGHTLIGHT_SET, [mode, brightness], timeout)

    async def get_nightlight(self, timeout: float = 5.0) -> NightlightState:
        """Fetch the current nightlight state."""
        response = await self._send_request(CALLBACK_NIGHTLIGHT_STATUS, timeout=timeout)
        args = response.get("payload", {}).get("callbackArgs", [])
        return NightlightState.from_raw(args)

    async def set_color_hsv(
        self,
        light: int,
        hue: int,
        saturation: int,
        brightness: int = 100,
        on: bool = True,
        count: int = 1,
        timeout: float = 5.0,
    ) -> None:
        """Set a color array (``light`` selector) to an HSV color.

        A single entry broadcasts across the array, but the firmware animates the
        fill; pass ``count`` = the number of LEDs to set them all at once instead.
        """
        leds = [
            ColorLedEntry(
                state=on, brightness=brightness, hue=hue, saturation=saturation
            )
            for _ in range(count)
        ]
        await self._set_color_hsv(light, leds, timeout=timeout)

    async def set_color_temperature(
        self,
        light: int,
        kelvin: int,
        brightness: int = 100,
        on: bool = True,
        count: int = 1,
        timeout: float = 5.0,
    ) -> None:
        """Set a color array (``light`` selector) to a white temperature.

        Unlike the HSV path, the firmware does not broadcast a single temperature
        entry across the array, so pass ``count`` = the number of LEDs to light
        them all (one identical entry per LED).
        """
        leds = [
            ColorLedEntry(state=on, brightness=brightness, temperature=kelvin)
            for _ in range(count)
        ]
        await self._set_color_temperature(light, leds, timeout)

    async def set_color_temperatures(
        self,
        light: int,
        temperatures: list[int],
        brightness: list[int] | None = None,
        states: list[bool] | None = None,
        timeout: float = 5.0,
    ) -> None:
        """Set a color array to a per-LED white temperature.

        ``temperatures`` is one kelvin per LED; ``brightness`` (0-100) and
        ``states`` are optional matching lists (default full + on).
        """
        leds = [
            ColorLedEntry(
                state=states[index] if states is not None else True,
                brightness=brightness[index] if brightness is not None else 100,
                temperature=kelvin,
            )
            for index, kelvin in enumerate(temperatures)
        ]
        await self._set_color_temperature(light, leds, timeout)

    async def set_color_pixels(
        self,
        light: int,
        colors: list[tuple[int, int]],
        brightness: list[int] | None = None,
        mode: int = 1,
        timeout: float = 5.0,
    ) -> None:
        """Set per-LED colors (and optionally the mode) by round-tripping the frame.

        ``colors`` is a list of ``(hue, saturation)`` applied to LEDs 0..N-1 in
        order; LEDs beyond the list — and the device's undocumented trailing
        fields — are left untouched. ``brightness``, if given, is a matching list
        of 0-100 levels applied to the same LEDs. ``mode`` selects static color
        (1) or an effect (:class:`ColorEffect`) that animates the palette.
        """
        state = await self._get_color(light, timeout)
        state.mode = int(mode)
        for index, (led, (hue, saturation)) in enumerate(zip(state.leds, colors)):
            led.state = True
            led.hue = hue
            led.saturation = saturation
            if brightness is not None and index < len(brightness):
                led.brightness = brightness[index]
        await self._send_request(
            CALLBACK_COLOR_LIGHT_TEMPERATURE, state.to_raw(), timeout
        )

    async def set_color_effect_pixels(
        self,
        light: int,
        colors: list[tuple[int, int]],
        effect: ColorEffect | int,
        speed: int,
        randomize: bool,
        level: int,
        brightness: list[int] | None = None,
        timeout: float = 5.0,
    ) -> None:
        """Run an animated effect over a per-LED palette.

        Sends ``[light, mode, [[state, brightness, [hue, sat]], ...], speed,
        randomize, level]`` — the per-LED color array followed by speed, the
        randomize flag, and a brightness level (used by the device only when
        randomizing).
        """
        leds = [
            ColorLedEntry(
                state=True,
                brightness=brightness[index] if brightness is not None else 100,
                hue=hue,
                saturation=saturation,
            )
            for index, (hue, saturation) in enumerate(colors)
        ]
        state = ColorLightState(light=light, mode=int(effect), leds=leds)
        payload = [*state.to_hsv_raw(), speed, int(randomize), level]
        await self._send_request(CALLBACK_COLOR_LIGHT_TEMPERATURE, payload, timeout)

    async def get_color(self, light: int, timeout: float = 5.0) -> ColorLightState:
        """Fetch a color array's state (``light`` selector).

        Raises ``InvisOutletCommandError`` if the device returns no data for that
        selector (e.g. no Aura attached).
        """
        return await self._get_color(light, timeout)

    async def _set_color_temperature(
        self, light: int, leds: list[ColorLedEntry], timeout: float = 5.0
    ) -> None:
        """Set a color light to static-temperature mode (callback 17, mode 2)."""
        state = ColorLightState(light=light, mode=2, leds=leds)
        await self._send_request(
            CALLBACK_COLOR_LIGHT_TEMPERATURE, state.to_temperature_raw(), timeout
        )

    async def _set_color_hsv(
        self, light: int, leds: list[ColorLedEntry], timeout: float = 5.0
    ) -> None:
        """Set a color light to static-HSV mode (callback 17, mode 1)."""
        state = ColorLightState(light=light, mode=1, leds=leds)
        await self._send_request(
            CALLBACK_COLOR_LIGHT_TEMPERATURE, state.to_hsv_raw(), timeout
        )

    async def _get_color(self, light: int, timeout: float = 5.0) -> ColorLightState:
        """Fetch a color light's state (callback 18)."""
        response = await self._send_request(CALLBACK_COLOR_LIGHT, [light], timeout)
        args = response.get("payload", {}).get("callbackArgs", [])
        if not isinstance(args, list) or len(args) < 3:
            raise InvisOutletCommandError(
                f"No color light at index {light}; this device may not have an Aura."
            )
        return ColorLightState.from_raw(args)

    async def get_available_updates(self, timeout: float = 5.0) -> AvailableUpdates:
        """Request available firmware updates."""
        response = await self._send_request(CALLBACK_UPDATES_GET, timeout=timeout)
        args = response.get("payload", {}).get("callbackArgs", {})
        return AvailableUpdates.from_raw(args)

    async def check_firmware(
        self,
        target: OtaTarget,
        model: str,
        hw_rev: str,
        current_fw_rev: str,
        variant: str | None = None,
        timeout: float = 10.0,
    ) -> FirmwareRelease | None:
        """Look up the latest firmware for a module from the update service.

        ``variant`` (a faceplate's ``type``, e.g. ``"Aura"``) takes precedence
        over ``model`` for the product code, since faceplates share a model name.
        Returns ``None`` for a model with no known product code (i.e. no known
        update channel). Unlike :meth:`get_available_updates`, this also yields
        the download URL and release notes.
        """
        product = _OTA_PRODUCT_CODES.get(variant) or _OTA_PRODUCT_CODES.get(model)
        if product is None:
            return None
        if self._session is None:
            raise InvisOutletConnectionError("Not connected")
        url = (
            f"{_OTA_CHECK_BASE}/{_OTA_MODULE[target]}/{product}"
            f"/{hw_rev}/{current_fw_rev}"
        )
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise InvisOutletConnectionError(
                f"Firmware check failed for {model}: {err}"
            ) from err
        return FirmwareRelease.from_raw(data, current_fw_rev)

    async def perform_ota_update(self, target: OtaTarget, method: int = 0) -> None:
        """Start an OTA update.

        Args:
            target: Which device to update (see :class:`OtaTarget`).
            method: For the InvisDeco, 0 = over its own Wi-Fi, 1 = via the
                InvisOutlet. Ignored for the InvisOutlet.

        Fire-and-forget: the device may not acknowledge before it gets busy
        starting the download, so this does not wait for a reply. Progress and
        result arrive asynchronously via ``on_ota_progress`` and
        ``on_ota_result``.
        """
        await self._send_command_noreply(CALLBACK_OTA_PERFORM, [int(target), method])
        self._ota_seen_progress.discard(target)
        self._arm_ota_stall(target)

    async def restart_invisdeco(self, timeout: float = 5.0) -> None:
        """Restart the attached InvisDeco sub-device."""
        await self._send_request(CALLBACK_RESTART_INVISDECO, timeout=timeout)

    async def reset_invisdeco(self, timeout: float = 5.0) -> None:
        """Reset the attached InvisDeco sub-device."""
        await self._send_request(CALLBACK_RESET_INVISDECO, timeout=timeout)

    async def calibrate_occupancy(
        self, duration_seconds: int, timeout: float = 5.0
    ) -> None:
        """Run occupancy-sensor calibration for the given duration."""
        await self._send_request(
            CALLBACK_OCCUPANCY_CALIBRATION, [duration_seconds], timeout
        )

    async def calibrate_temp_humidity(
        self,
        temperature_celsius: float,
        humidity_percent: float,
        timeout: float = 5.0,
    ) -> None:
        """Calibrate temperature and relative humidity to reference values.

        The device expects millidegrees and millipercent; this converts for you.
        """
        await self._send_request(
            CALLBACK_TEMP_HUMIDITY_CALIBRATION,
            [round(temperature_celsius * 1000), round(humidity_percent * 1000)],
            timeout,
        )

    def on_ota_progress(
        self, callback: Callable[[OtaProgress], None]
    ) -> Callable[[], None]:
        """Register a callback for server-pushed OTA progress updates.

        Returns a function to unregister the callback.
        """

        def _wrapper(msg: dict[str, Any]) -> None:
            args = msg.get("payload", {}).get("callbackArgs", [])
            if len(args) >= 2:
                callback(OtaProgress.from_raw(args))

        return self._add_listener(CALLBACK_OTA_PROGRESS, _wrapper)

    def on_ota_result(
        self, callback: Callable[[OtaResult], None]
    ) -> Callable[[], None]:
        """Register a callback for OTA result updates. Returns an unsubscribe.

        Results are gated to paper over a firmware quirk: the device emits a
        junk ``status=0`` result at the start of every update, before any
        download. Such a pre-progress ``status=0`` is suppressed; a stall (no
        progress within :data:`_OTA_STALL_TIMEOUT`) is instead reported as a
        synthesized ``status=0`` result. Callbacks therefore fire exactly once
        per update: a real ``status=1`` success, a real failure after progress
        began, or the synthesized stall failure.
        """
        return _add_to(self._ota_result_callbacks, callback)

    def _notify_ota_result(self, result: OtaResult) -> None:
        """Fan a (real or synthesized) result out to the gated subscribers."""
        _fire(self._ota_result_callbacks, "on_ota_result", result)

    def _on_raw_ota_progress(self, msg: dict[str, Any]) -> None:
        """Internal: mark progress seen and reset the stall timer."""
        args = msg.get("payload", {}).get("callbackArgs", [])
        if len(args) < 2:
            return
        target = target_for_device_type(OtaProgress.from_raw(args).device_type)
        if target is None:
            return
        self._ota_seen_progress.add(target)
        self._arm_ota_stall(target)

    def _on_raw_ota_result(self, msg: dict[str, Any]) -> None:
        """Internal: gate a result push before notifying subscribers."""
        args = msg.get("payload", {}).get("callbackArgs", [])
        if len(args) < 2:
            return
        result = OtaResult.from_raw(args)
        if result.device_type == _OTA_SUBPHASE_DEVICE_TYPE and result.success:
            # A sub-phase (WWW partition) finished, not the whole update; the
            # terminal phase (device_type 1) follows. Leave the stall timer
            # running so it spans into that phase rather than ending here.
            return
        target = target_for_device_type(result.device_type)
        if (
            target is not None
            and not result.success
            and (target not in self._ota_seen_progress)
        ):
            # Spurious pre-progress status-0: suppress, leaving the stall timer
            # running so a genuine silent failure is still caught.
            _LOGGER.debug(
                "Suppressing spurious pre-progress OTA result for %s", target.name
            )
            return
        # Terminal: success, or a real failure once progress had started.
        if target is not None:
            self._cancel_ota_stall(target)
            self._ota_seen_progress.discard(target)
        self._notify_ota_result(result)

    def _arm_ota_stall(self, target: OtaTarget) -> None:
        """(Re)start the stall timer for a target."""
        self._cancel_ota_stall(target)
        self._ota_stall[target] = asyncio.get_event_loop().call_later(
            _OTA_STALL_TIMEOUT, partial(self._on_ota_stall, target)
        )

    def _cancel_ota_stall(self, target: OtaTarget) -> None:
        """Cancel a target's stall timer if armed."""
        handle = self._ota_stall.pop(target, None)
        if handle is not None:
            handle.cancel()

    def _on_ota_stall(self, target: OtaTarget) -> None:
        """Fire a synthesized failure result when an update stalls."""
        self._ota_stall.pop(target, None)
        self._ota_seen_progress.discard(target)
        _LOGGER.warning(
            "OTA update for %s stalled (no progress for %ss); reporting failure",
            target.name,
            _OTA_STALL_TIMEOUT,
        )
        self._notify_ota_result(OtaResult(device_type=int(target), status=0))

    def _build_message(
        self, packet_id: int, callback_name: int, callback_args: Any
    ) -> str:
        """Serialize a request envelope."""
        payload: dict[str, Any] = {"callbackName": callback_name}
        if callback_args is not None:
            payload["callbackArgs"] = callback_args
        return json.dumps({"packetID": packet_id, "payload": payload})

    async def _send_request(
        self,
        callback_name: int,
        callback_args: Any = None,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Send a request and wait for the matching response by packet ID.

        Raises ``InvisOutletCommandError`` if the device reports failure
        (``PUBACK == 0``) and ``InvisOutletTimeoutError`` on timeout.
        """
        if not self._ws:
            raise InvisOutletConnectionError("Not connected")

        packet_id = random.randint(100000, 999999)
        message = self._build_message(packet_id, callback_name, callback_args)

        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_event_loop().create_future()
        )
        self._pending_requests[packet_id] = future

        try:
            await self._ws.send_str(message)
            response = await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as err:
            raise InvisOutletTimeoutError(
                f"Timeout waiting for response to callbackName={callback_name}"
            ) from err
        finally:
            self._pending_requests.pop(packet_id, None)

        if response.get("PUBACK") == 0:
            raise InvisOutletCommandError(
                f"Device reported failure for callbackName={callback_name}"
            )
        return response

    async def _send_command_noreply(
        self, callback_name: int, callback_args: Any = None
    ) -> None:
        """Send a fire-and-forget command for which the device sends no response.

        Used for callbacks 5/6/7 (restart, network reset, factory reset).
        """
        if not self._ws:
            raise InvisOutletConnectionError("Not connected")

        packet_id = random.randint(100000, 999999)
        message = self._build_message(packet_id, callback_name, callback_args)
        await self._ws.send_str(message)

    async def _read_loop(self) -> None:
        """Read messages from the WebSocket and dispatch them."""
        assert self._ws is not None

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        _LOGGER.warning("Received invalid JSON: %s", msg.data[:200])
                        continue
                    self._dispatch(data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", self._ws.exception())
                    break
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    _LOGGER.debug("WebSocket closed by device")
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Error in WebSocket read loop")

    def _dispatch(self, msg: dict[str, Any]) -> None:
        """Route a parsed message to the right handler."""
        packet_id = msg.get("packetID")
        callback_name = msg.get("payload", {}).get("callbackName")

        _LOGGER.debug("Received callbackName=%s packetID=%s", callback_name, packet_id)

        # Check if this is a response to a pending request
        if packet_id and packet_id in self._pending_requests:
            future = self._pending_requests[packet_id]
            if not future.done():
                future.set_result(msg)
            return

        # Otherwise dispatch to listeners
        if callback_name is not None:
            for listener in self._listeners.get(callback_name, []):
                try:
                    listener(msg)
                except Exception:
                    _LOGGER.exception(
                        "Error in listener for callbackName=%s", callback_name
                    )

    def _add_listener(
        self, callback_name: int, callback: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Add a listener and return an unsubscribe function."""
        self._listeners.setdefault(callback_name, []).append(callback)

        def _remove() -> None:
            self._listeners.get(callback_name, []).remove(callback)

        return _remove
