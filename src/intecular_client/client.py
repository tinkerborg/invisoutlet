"""Client for communicating with Intecular devices over WebSocket."""

import asyncio
import json
import logging
import random
from collections.abc import Callable
from enum import IntEnum
from typing import Any

import aiohttp

from .exceptions import (
    IntecularCommandError,
    IntecularConnectionError,
    IntecularTimeoutError,
)
from .models import (
    AccessoryName,
    AvailableUpdates,
    ColorLedEntry,
    ColorLightState,
    DeviceConfig,
    DeviceInfo,
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
    """Which device an OTA firmware update targets (callback 21)."""

    INVISOUTLET = 0
    INVISDECO = 1


# Color-light array selector for the nightlight (the first ``callbackArgs``
# element of callbacks 17/18), confirmed by the API docs. Internal — callers use
# the ``*_nightlight_color`` methods rather than addressing the array directly.
_LIGHT_NIGHTLIGHT = 5


class IntecularClient:
    """Client for Intecular smart outlet devices over WebSocket."""

    def __init__(self, host: str, port: int = 80) -> None:
        """Initialize the client."""
        self.host = host
        self.port = port
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._listeners: dict[int, list[Callable[[dict[str, Any]], None]]] = {}
        self._pending_requests: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._read_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Connect to the device."""
        self._session = aiohttp.ClientSession()
        try:
            self._ws = await asyncio.wait_for(
                self._session.ws_connect(f"ws://{self.host}:{self.port}/ws"),
                timeout=10.0,
            )
        except TimeoutError as err:
            await self._session.close()
            self._session = None
            raise IntecularTimeoutError(
                f"Timeout connecting to {self.host}:{self.port}"
            ) from err
        except (OSError, aiohttp.ClientError) as err:
            await self._session.close()
            self._session = None
            raise IntecularConnectionError(
                f"Cannot connect to {self.host}:{self.port}: {err}"
            ) from err

        self._read_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        """Close the connection."""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self._session:
            await self._session.close()
            self._session = None

        # Cancel any pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

    async def __aenter__(self) -> "IntecularClient":
        """Enter async context manager."""
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit async context manager."""
        await self.close()

    def on_sensor_data(self, callback: Callable[[SensorData], None]) -> Callable[[], None]:
        """Register a callback for sensor data updates.

        Returns a function to unregister the callback.
        """
        def _wrapper(msg: dict[str, Any]) -> None:
            args = msg.get("payload", {}).get("callbackArgs", [])
            if len(args) >= 2 and isinstance(args[1], dict):
                callback(SensorData.from_raw(args[1]))

        return self._add_listener(CALLBACK_SENSOR_DATA, _wrapper)

    def on_message(
        self, callback_name: int, callback: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Register a callback for a specific message type.

        Returns a function to unregister the callback.
        """
        return self._add_listener(callback_name, callback)

    async def set_outlet(
        self, outlet: int, on: bool, timeout: float = 5.0
    ) -> dict[str, Any]:
        """Set the state of an outlet.

        Args:
            outlet: Outlet number (1 or 2).
            on: True to turn on, False to turn off.

        """
        return await self._send_request(
            CALLBACK_OUTLET_SET, [outlet, int(on)], timeout
        )

    async def get_config(self, timeout: float = 5.0) -> DeviceConfig:
        """Request device configuration."""
        response = await self._send_request(CALLBACK_CONFIG_GET, timeout=timeout)
        args = response.get("payload", {}).get("callbackArgs", {})
        return DeviceConfig.from_raw(args)

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
    ) -> dict[str, Any]:
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
        return await self._send_request(
            CALLBACK_CONFIG_SET, [config.to_raw()], timeout
        )

    async def get_device_info(self, timeout: float = 5.0) -> DeviceInfo:
        """Request device information."""
        response = await self._send_request(CALLBACK_DEVICE_INFO, timeout=timeout)
        args = response.get("payload", {}).get("callbackArgs", {})
        return DeviceInfo.from_raw(args, self.host, self.port)

    async def get_accessory_names(
        self, timeout: float = 5.0
    ) -> list[AccessoryName]:
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
    ) -> dict[str, Any]:
        """Set the user-assigned accessory names."""
        return await self._send_request(
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
        response = await self._send_request(
            CALLBACK_OUTLET_STATUS, timeout=timeout
        )
        args = response.get("payload", {}).get("callbackArgs", [])
        return OutletStatus.from_raw(args)

    async def set_nightlight(
        self, mode: int, brightness: int, timeout: float = 5.0
    ) -> dict[str, Any]:
        """Control the nightlight.

        Args:
            mode: Nightlight mode (0 = off, >0 = on).
            brightness: Brightness 0-100.

        """
        return await self._send_request(
            CALLBACK_NIGHTLIGHT_SET, [mode, brightness], timeout
        )

    async def get_nightlight(self, timeout: float = 5.0) -> NightlightState:
        """Fetch the current nightlight state."""
        response = await self._send_request(
            CALLBACK_NIGHTLIGHT_STATUS, timeout=timeout
        )
        args = response.get("payload", {}).get("callbackArgs", [])
        return NightlightState.from_raw(args)

    async def set_nightlight_color(
        self,
        hue: int,
        saturation: int,
        brightness: int = 100,
        on: bool = True,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Set the nightlight color array to an HSV color (Aura faceplate)."""
        led = ColorLedEntry(
            state=on, brightness=brightness, hue=hue, saturation=saturation
        )
        return await self._set_color_hsv(_LIGHT_NIGHTLIGHT, [led], timeout)

    async def set_nightlight_temperature(
        self,
        kelvin: int,
        brightness: int = 100,
        on: bool = True,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Set the nightlight color array to a white temperature (Aura faceplate)."""
        led = ColorLedEntry(state=on, brightness=brightness, temperature=kelvin)
        return await self._set_color_temperature(_LIGHT_NIGHTLIGHT, [led], timeout)

    async def get_nightlight_color(self, timeout: float = 5.0) -> ColorLightState:
        """Fetch the nightlight color array's state (Aura faceplate).

        Raises ``IntecularCommandError`` if the device returns no light data,
        e.g. there is no color nightlight (no Aura attached).
        """
        return await self._get_color(_LIGHT_NIGHTLIGHT, timeout)

    async def _set_color_temperature(
        self, light: int, leds: list[ColorLedEntry], timeout: float = 5.0
    ) -> dict[str, Any]:
        """Set a color light to static-temperature mode (callback 17, mode 2)."""
        state = ColorLightState(light=light, mode=2, leds=leds)
        return await self._send_request(
            CALLBACK_COLOR_LIGHT_TEMPERATURE, state.to_temperature_raw(), timeout
        )

    async def _set_color_hsv(
        self, light: int, leds: list[ColorLedEntry], timeout: float = 5.0
    ) -> dict[str, Any]:
        """Set a color light to static-HSV mode (callback 17, mode 1)."""
        state = ColorLightState(light=light, mode=1, leds=leds)
        return await self._send_request(
            CALLBACK_COLOR_LIGHT_TEMPERATURE, state.to_hsv_raw(), timeout
        )

    async def _get_color(
        self, light: int, timeout: float = 5.0
    ) -> ColorLightState:
        """Fetch a color light's state (callback 18)."""
        response = await self._send_request(
            CALLBACK_COLOR_LIGHT, [light], timeout
        )
        args = response.get("payload", {}).get("callbackArgs", [])
        if not isinstance(args, list) or len(args) < 3:
            raise IntecularCommandError(
                f"No color light at index {light}; this device may not have an Aura."
            )
        return ColorLightState.from_raw(args)

    async def get_available_updates(
        self, timeout: float = 5.0
    ) -> AvailableUpdates:
        """Request available firmware updates."""
        response = await self._send_request(CALLBACK_UPDATES_GET, timeout=timeout)
        args = response.get("payload", {}).get("callbackArgs", {})
        return AvailableUpdates.from_raw(args)

    async def perform_ota_update(
        self, target: OtaTarget, method: int = 0, timeout: float = 5.0
    ) -> dict[str, Any]:
        """Start an OTA update.

        Args:
            target: Which device to update (see :class:`OtaTarget`).
            method: Update method identifier.

        Progress and result arrive asynchronously via ``on_ota_progress`` and
        ``on_ota_result``.
        """
        return await self._send_request(
            CALLBACK_OTA_PERFORM, [int(target), method], timeout
        )

    async def restart_invisdeco(self, timeout: float = 5.0) -> dict[str, Any]:
        """Restart the attached InvisDeco sub-device."""
        return await self._send_request(
            CALLBACK_RESTART_INVISDECO, timeout=timeout
        )

    async def reset_invisdeco(self, timeout: float = 5.0) -> dict[str, Any]:
        """Reset the attached InvisDeco sub-device."""
        return await self._send_request(
            CALLBACK_RESET_INVISDECO, timeout=timeout
        )

    async def calibrate_occupancy(
        self, duration_seconds: int, timeout: float = 5.0
    ) -> dict[str, Any]:
        """Run occupancy-sensor calibration for the given duration."""
        return await self._send_request(
            CALLBACK_OCCUPANCY_CALIBRATION, [duration_seconds], timeout
        )

    async def calibrate_temp_humidity(
        self,
        temperature_celsius: float,
        humidity_percent: float,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Calibrate temperature and relative humidity to reference values.

        The device expects millidegrees and millipercent; this converts for you.
        """
        return await self._send_request(
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
            if len(args) >= 3:
                callback(OtaProgress.from_raw(args))

        return self._add_listener(CALLBACK_OTA_PROGRESS, _wrapper)

    def on_ota_result(
        self, callback: Callable[[OtaResult], None]
    ) -> Callable[[], None]:
        """Register a callback for server-pushed OTA result updates.

        Returns a function to unregister the callback.
        """

        def _wrapper(msg: dict[str, Any]) -> None:
            args = msg.get("payload", {}).get("callbackArgs", [])
            if len(args) >= 3:
                callback(OtaResult.from_raw(args))

        return self._add_listener(CALLBACK_OTA_RESULT, _wrapper)

    async def send_command(
        self, callback_name: int, callback_args: Any = None, timeout: float = 5.0
    ) -> dict[str, Any]:
        """Send a command and wait for a response."""
        return await self._send_request(callback_name, callback_args, timeout)

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

        Raises ``IntecularCommandError`` if the device reports failure
        (``PUBACK == 0``) and ``IntecularTimeoutError`` on timeout.
        """
        if not self._ws:
            raise IntecularConnectionError("Not connected")

        packet_id = random.randint(100000, 999999)
        message = self._build_message(packet_id, callback_name, callback_args)

        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending_requests[packet_id] = future

        try:
            await self._ws.send_str(message)
            response = await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as err:
            raise IntecularTimeoutError(
                f"Timeout waiting for response to callbackName={callback_name}"
            ) from err
        finally:
            self._pending_requests.pop(packet_id, None)

        if response.get("PUBACK") == 0:
            raise IntecularCommandError(
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
            raise IntecularConnectionError("Not connected")

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
                    _LOGGER.exception("Error in listener for callbackName=%s", callback_name)

    def _add_listener(
        self, callback_name: int, callback: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Add a listener and return an unsubscribe function."""
        self._listeners.setdefault(callback_name, []).append(callback)

        def _remove() -> None:
            self._listeners.get(callback_name, []).remove(callback)

        return _remove
