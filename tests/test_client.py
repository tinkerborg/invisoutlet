"""Tests for the InvisOutletClient WebSocket client."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import pytest

from invisoutlet import (
    AccessoryName,
    InvisOutletClient,
    InvisOutletCommandError,
    InvisOutletConnectionError,
    InvisOutletTimeoutError,
    OtaProgress,
    OtaResult,
    OtaTarget,
    OutletStatus,
    SensorData,
)
from invisoutlet.client import (
    CALLBACK_FACTORY_RESET,
    CALLBACK_OTA_PROGRESS,
    CALLBACK_OTA_RESULT,
    CALLBACK_OUTLET_STATUS,
    CALLBACK_RESET_NETWORK,
    CALLBACK_RESTART,
    CALLBACK_SENSOR_DATA,
    ColorEffect,
    LIGHT_NIGHTLIGHT,
    target_for_device_type,
)

from .conftest import FakeMessage, FakeSession, FakeWebSocket


def _last(ws: FakeWebSocket) -> dict:
    """Return the payload of the most recent request."""
    return ws.sent[-1]["payload"]


def _raise(*_args: object) -> None:
    """A callback that always raises, to test error isolation."""
    raise ValueError("boom")


async def test_set_outlet_framing(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """set_outlet should send callbackName 10 with [outlet, 0/1]."""
    client, ws = connected_client
    await client.set_outlet(2, True)
    payload = _last(ws)
    assert payload["callbackName"] == 10
    assert payload["callbackArgs"] == [2, 1]
    assert "packetID" in ws.sent[-1]


async def test_get_config(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """get_config should parse the nested response into a DeviceConfig."""
    client, ws = connected_client
    ws.responses[1] = {"acc_prefs": {"pmIndicatorBrightness": 60, "capacitiveCtrl": 1}}
    config = await client.get_config()
    assert config.pm_indicator_brightness == 60
    assert config.capacitive_ctrl is True


async def test_set_config_builds_nested_payload(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """set_config should send only the provided fields, nested correctly."""
    client, ws = connected_client
    await client.set_config(outlet_power_indicator_on=False, mqtt_qos=2)
    payload = _last(ws)
    assert payload["callbackName"] == 2
    assert payload["callbackArgs"] == [
        {"acc_prefs": {"outletPwrIndicatorOn": 0}, "sys_prefs": {"mqtt": {"qos": 2}}}
    ]


async def test_get_device_info(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """get_device_info should parse IM and inject host/port."""
    client, ws = connected_client
    ws.responses[12] = {"IM": {"sn": "S1", "MAC": "aa", "device": "InvisOutlet"}}
    info = await client.get_device_info()
    assert info.serial_number == "S1"
    assert info.host == "device.local"
    assert info.port == 80


async def test_accessory_names_round_trip(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """get/set accessory names should use the documented framing."""
    client, ws = connected_client
    # Real firmware returns a bare list of name objects.
    ws.responses[3] = [{"accessory": 1, "name": "Outlet 1"}]
    names = await client.get_accessory_names()
    assert names == [AccessoryName(accessory=1, name="Outlet 1")]

    # The documented wrapped shape is also accepted.
    ws.responses[3] = {"payload": [{"accessory": 2, "name": "Fan"}]}
    assert await client.get_accessory_names() == [AccessoryName(accessory=2, name="Fan")]

    await client.set_accessory_names([AccessoryName(accessory=2, name="Fan")])
    payload = _last(ws)
    assert payload["callbackName"] == 4
    assert payload["callbackArgs"] == [{"accessory": 2, "name": "Fan"}]


@pytest.mark.parametrize(
    ("method", "callback"),
    [
        ("restart", CALLBACK_RESTART),
        ("reset_network", CALLBACK_RESET_NETWORK),
        ("factory_reset", CALLBACK_FACTORY_RESET),
    ],
)
async def test_no_reply_commands(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
    method: str,
    callback: int,
) -> None:
    """Restart/reset commands must return without awaiting a response."""
    client, ws = connected_client
    # Device sends nothing back; the call must still complete promptly.
    ws.no_reply.add(callback)
    await asyncio.wait_for(getattr(client, method)(), timeout=1.0)
    assert _last(ws)["callbackName"] == callback
    assert "callbackArgs" not in _last(ws)


async def test_get_outlet_status(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """get_outlet_status should parse the positional array."""
    client, ws = connected_client
    ws.responses[9] = [1, 0]
    status = await client.get_outlet_status()
    assert status.is_on(1) is True
    assert status.is_on(2) is False


async def test_nightlight(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """set/get nightlight should use [mode, brightness]."""
    client, ws = connected_client
    await client.set_nightlight(1, 75)
    assert _last(ws)["callbackArgs"] == [1, 75]

    ws.responses[15] = [1, 75]
    state = await client.get_nightlight()
    assert state.mode == 1
    assert state.brightness == 75


async def test_set_color_temperature_and_get(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """set_color_temperature (17) and get_color (18)."""
    client, ws = connected_client
    await client.set_color_temperature(LIGHT_NIGHTLIGHT, 3500, brightness=90)
    payload = _last(ws)
    assert payload["callbackName"] == 17
    assert payload["callbackArgs"] == [5, 2, [[1, 90, 3500]]]

    ws.responses[18] = [5, 2, [[1, 100, [200, 50], 4000]]]
    state = await client.get_color(LIGHT_NIGHTLIGHT)
    assert state.leds[0].hue == 200
    assert state.leds[0].temperature == 4000


async def test_set_color_hsv(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """set_color_hsv (17) should frame as mode 1 with [[state, bri, [hue, sat]]]."""
    client, ws = connected_client
    await client.set_color_hsv(LIGHT_NIGHTLIGHT, 200, 80, brightness=90)
    payload = _last(ws)
    assert payload["callbackName"] == 17
    assert payload["callbackArgs"] == [5, 1, [[1, 90, [200, 80]]]]


async def test_set_color_pixels(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """set_color_pixels round-trips: recolour LEDs 0..N in order, keep the rest."""
    client, ws = connected_client
    # Current frame: 3 LEDs (all the same) + trailing fields.
    ws.responses[18] = [5, 1, [[1, 40, [27, 35], 4000]] * 3, 1, 0, 40]
    # Two colours -> LEDs 0,1 recoloured; LED 2 kept; mode set to Rainbow.
    await client.set_color_pixels(
        LIGHT_NIGHTLIGHT, [(10, 100), (120, 50)], mode=ColorEffect.RAINBOW
    )
    payload = _last(ws)
    assert payload["callbackName"] == 17
    assert payload["callbackArgs"] == [
        5,
        6,
        [
            [1, 40, [10, 100], 4000],
            [1, 40, [120, 50], 4000],
            [1, 40, [27, 35], 4000],
        ],
        1,
        0,
        40,
    ]


async def test_get_color_missing_raises(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """get_color raises a clear error when no light data comes back."""
    client, ws = connected_client
    ws.responses[18] = []  # device returns nothing (e.g. no Aura attached)
    with pytest.raises(InvisOutletCommandError):
        await client.get_color(LIGHT_NIGHTLIGHT)


async def test_available_updates(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """get_available_updates should parse the IM/PM revisions."""
    client, ws = connected_client
    ws.responses[20] = {"IM": {"fw_rev": "1.0", "available_fw_rev": "1.1"}}
    updates = await client.get_available_updates()
    assert updates.update_available is True


async def test_perform_ota_update_framing(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """perform_ota_update should send [target, method]."""
    client, ws = connected_client
    ws.responses[21] = [1, 1]
    await client.perform_ota_update(OtaTarget.INVISDECO, 0)
    assert _last(ws)["callbackArgs"] == [2, 0]


def _push_ota(ws: FakeWebSocket, callback: int, args: list[int]) -> None:
    """Inject an OTA progress/result push."""
    ws.push({"packetID": 1, "payload": {"callbackName": callback, "callbackArgs": args}})


async def test_ota_result_suppresses_spurious_pre_progress(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """A status-0 result before any progress is the firmware's junk start signal."""
    client, ws = connected_client
    results: list[OtaResult] = []
    client.on_ota_result(results.append)
    _push_ota(ws, CALLBACK_OTA_RESULT, [2, 0])
    await asyncio.sleep(0.01)
    assert results == []


async def test_ota_result_forwards_failure_after_progress(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """A status-0 result once progress has started is a genuine failure."""
    client, ws = connected_client
    results: list[OtaResult] = []
    client.on_ota_result(results.append)
    _push_ota(ws, CALLBACK_OTA_PROGRESS, [2, 5])
    await asyncio.sleep(0.01)
    _push_ota(ws, CALLBACK_OTA_RESULT, [2, 0])
    await asyncio.sleep(0.01)
    assert len(results) == 1
    assert results[0].device_type == 2
    assert results[0].success is False


async def test_ota_result_forwards_success(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """A status-1 result is always forwarded as a success."""
    client, ws = connected_client
    results: list[OtaResult] = []
    client.on_ota_result(results.append)
    _push_ota(ws, CALLBACK_OTA_RESULT, [2, 1])
    await asyncio.sleep(0.01)
    assert len(results) == 1
    assert results[0].success is True


async def test_ota_result_suppresses_www_subphase(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """A device_type-3 (WWW partition) success is a sub-phase, not terminal."""
    client, ws = connected_client
    results: list[OtaResult] = []
    client.on_ota_result(results.append)
    _push_ota(ws, CALLBACK_OTA_RESULT, [3, 1])  # WWW phase done
    await asyncio.sleep(0.01)
    assert results == []  # not forwarded
    _push_ota(ws, CALLBACK_OTA_RESULT, [1, 1])  # main phase done -> terminal
    await asyncio.sleep(0.01)
    assert len(results) == 1
    assert results[0].device_type == 1
    assert results[0].success is True


async def test_ota_stall_synthesizes_failure(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No progress within the stall timeout yields a synthesized failure result."""
    client, ws = connected_client
    monkeypatch.setattr("invisoutlet.client._OTA_STALL_TIMEOUT", 0.05)
    results: list[OtaResult] = []
    client.on_ota_result(results.append)
    await client.perform_ota_update(OtaTarget.INVISDECO, 0)
    await asyncio.sleep(0.1)
    assert len(results) == 1
    assert results[0].device_type == 2
    assert results[0].success is False


async def test_ota_progress_resets_stall_timer(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each progress push pushes the stall deadline back."""
    client, ws = connected_client
    monkeypatch.setattr("invisoutlet.client._OTA_STALL_TIMEOUT", 0.08)
    results: list[OtaResult] = []
    client.on_ota_result(results.append)
    await client.perform_ota_update(OtaTarget.INVISDECO, 0)
    # Keep progress flowing faster than the timeout; no failure should fire.
    for pct in (10, 20, 30):
        await asyncio.sleep(0.04)
        _push_ota(ws, CALLBACK_OTA_PROGRESS, [2, pct])
    await asyncio.sleep(0.01)
    assert results == []


async def test_calibrate_temp_humidity_converts_to_millis(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """Calibration values should be sent in milli-units."""
    client, ws = connected_client
    await client.calibrate_temp_humidity(25.0, 50.0)
    assert _last(ws)["callbackArgs"] == [25000, 50000]


async def test_calibrate_occupancy(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """Occupancy calibration should send [durationSeconds]."""
    client, ws = connected_client
    await client.calibrate_occupancy(30)
    assert _last(ws)["callbackArgs"] == [30]


async def test_puback_failure_raises(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """A PUBACK of 0 should raise InvisOutletCommandError."""
    client, ws = connected_client
    ws.puback = 0
    with pytest.raises(InvisOutletCommandError):
        await client.set_outlet(1, True)


async def test_timeout_raises(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """A response that never arrives should raise InvisOutletTimeoutError."""
    client, ws = connected_client
    ws.no_reply.add(9)  # callback that normally expects a reply
    with pytest.raises(InvisOutletTimeoutError):
        await client.get_outlet_status(timeout=0.05)


async def test_not_connected_raises() -> None:
    """Sending without a connection should raise InvisOutletConnectionError."""
    client = InvisOutletClient("device.local")
    with pytest.raises(InvisOutletConnectionError):
        await client.set_outlet(1, True)


async def test_sensor_data_push_dispatch(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """on_sensor_data should fire for server-pushed sensor messages."""
    client, ws = connected_client
    received: list[SensorData] = []
    unsub = client.on_sensor_data(received.append)

    ws.push(
        {
            "packetID": 1,
            "payload": {
                "callbackName": CALLBACK_SENSOR_DATA,
                "callbackArgs": [0, {"temp_celsius": 20.0}],
            },
        }
    )
    await asyncio.sleep(0.01)
    assert len(received) == 1
    assert received[0].temperature == 20.0

    unsub()
    ws.push(
        {
            "packetID": 2,
            "payload": {
                "callbackName": CALLBACK_SENSOR_DATA,
                "callbackArgs": [0, {"temp_celsius": 99.0}],
            },
        }
    )
    await asyncio.sleep(0.01)
    assert len(received) == 1  # unsubscribed, no new events


async def test_on_outlet_status_push(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """on_outlet_status should fire for server-pushed outlet messages."""
    client, ws = connected_client
    received: list[OutletStatus] = []
    client.on_outlet_status(received.append)

    ws.push(
        {
            "packetID": 1,
            "payload": {
                "callbackName": CALLBACK_OUTLET_STATUS,
                "callbackArgs": [1, 0],
            },
        }
    )
    await asyncio.sleep(0.01)
    assert len(received) == 1
    assert received[0].outlets == [True, False]


async def test_auto_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dropped connection is re-established and listeners keep firing."""
    monkeypatch.setattr("invisoutlet.client._RECONNECT_INITIAL_DELAY", 0.01)

    session = FakeSession()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    session.queue_ws(ws1)
    session.queue_ws(ws2)

    client = InvisOutletClient("device.local")
    client._session = session  # type: ignore[assignment]

    received: list[SensorData] = []
    connects: list[int] = []
    disconnects: list[int] = []
    client.on_sensor_data(received.append)
    client.on_connect(lambda: connects.append(1))
    client.on_disconnect(lambda: disconnects.append(1))

    await client.connect()
    assert client._ws is ws1

    # Drop the first connection; the supervisor should reconnect to ws2.
    await ws1.close()
    for _ in range(50):
        await asyncio.sleep(0.01)
        if client._ws is ws2:
            break
    assert client._ws is ws2
    assert len(connects) >= 2  # initial connect + reconnect
    assert len(disconnects) >= 1

    # The listener registered before the drop still fires on the new connection.
    ws2.push(
        {
            "payload": {
                "callbackName": CALLBACK_SENSOR_DATA,
                "callbackArgs": [0, {"temp_celsius": 21.0}],
            }
        }
    )
    await asyncio.sleep(0.02)
    assert received and received[-1].temperature == 21.0

    await client.close()


async def test_ota_push_dispatch(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """on_ota_progress and on_ota_result should fire for pushed events."""
    client, ws = connected_client
    progress: list[OtaProgress] = []
    results: list[OtaResult] = []
    client.on_ota_progress(progress.append)
    client.on_ota_result(results.append)

    ws.push(
        {
            "packetID": 1,
            "payload": {"callbackName": CALLBACK_OTA_PROGRESS, "callbackArgs": [1, 90]},
        }
    )
    ws.push(
        {
            "packetID": 2,
            "payload": {"callbackName": CALLBACK_OTA_RESULT, "callbackArgs": [1, 1]},
        }
    )
    await asyncio.sleep(0.01)
    assert progress[0].progress == 90
    assert results[0].success is True


# --- connection lifecycle -------------------------------------------------


def test_target_for_device_type_unknown() -> None:
    """An unrecognized OTA device_type maps to no target."""
    assert target_for_device_type(99) is None
    assert target_for_device_type(1) is OtaTarget.INVISOUTLET
    assert target_for_device_type(3) is OtaTarget.INVISOUTLET
    assert target_for_device_type(2) is OtaTarget.INVISDECO


async def test_connect_initial_failure_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed initial connect raises and leaves no dangling session."""
    # No queued socket → FakeSession.ws_connect raises like a refused connection.
    monkeypatch.setattr("invisoutlet.client.aiohttp.ClientSession", FakeSession)
    client = InvisOutletClient("device.local")
    with pytest.raises(InvisOutletConnectionError):
        await client.connect()
    assert client._session is None
    assert client._read_task is None


async def test_connect_timeout_wraps_error() -> None:
    """A timed-out handshake surfaces as InvisOutletTimeoutError."""

    class TimeoutSession(FakeSession):
        async def ws_connect(self, url: str, **kwargs: object) -> FakeWebSocket:
            raise TimeoutError

    client = InvisOutletClient("device.local")
    client._session = TimeoutSession()  # type: ignore[assignment]
    with pytest.raises(InvisOutletTimeoutError):
        await client.connect()


async def test_async_context_manager() -> None:
    """`async with` connects on enter and closes on exit."""
    client = InvisOutletClient("device.local")
    session = FakeSession()
    ws = FakeWebSocket()
    session.queue_ws(ws)
    client._session = session  # type: ignore[assignment]

    async with client as entered:
        assert entered is client
        assert client._ws is ws

    assert client._ws is None
    assert client._closing is True


async def test_close_cancels_pending_requests(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """Outstanding request futures are cancelled and cleared on close."""
    client, _ws = connected_client
    future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
    client._pending_requests[123] = future
    await client.close()
    assert future.cancelled()
    assert client._pending_requests == {}


async def test_handle_disconnect_fails_pending_and_tolerates_close_error(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """A disconnect fails in-flight requests even if the socket close errors."""
    client, _ws = connected_client

    class BadWs:
        async def close(self) -> None:
            raise RuntimeError("teardown boom")

    client._ws = BadWs()  # type: ignore[assignment]
    disconnects: list[int] = []
    client.on_disconnect(lambda: disconnects.append(1))
    future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
    client._pending_requests[1] = future

    await client._handle_disconnect()

    assert future.done()
    with pytest.raises(InvisOutletConnectionError):
        future.result()
    assert disconnects == [1]


async def test_reconnect_retries_after_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the first reconnect attempt fails, it backs off and retries."""
    monkeypatch.setattr("invisoutlet.client._RECONNECT_INITIAL_DELAY", 0.01)
    session = FakeSession()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    session.queue_ws(ws1)

    client = InvisOutletClient("device.local")
    client._session = session  # type: ignore[assignment]
    await client.connect()
    assert client._ws is ws1

    # Drop with nothing queued: reconnect attempts fail and back off.
    await ws1.close()
    await asyncio.sleep(0.05)
    assert client._ws is None

    # Provide a socket; the next attempt should succeed.
    session.queue_ws(ws2)
    for _ in range(100):
        await asyncio.sleep(0.01)
        if client._ws is ws2:
            break
    assert client._ws is ws2

    await client.close()


async def test_callback_unsubscribe_and_error_isolation(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """A raising connect callback is isolated; unsubscribe is idempotent."""
    client, _ws = connected_client
    calls: list[int] = []
    unsub_boom = client.on_connect(_raise)
    client.on_connect(lambda: calls.append(1))

    client._notify_connected()  # both fire; the raise is logged and swallowed
    assert calls == [1]

    unsub_boom()
    unsub_boom()  # second removal is a harmless no-op


async def test_send_command_noreply_not_connected() -> None:
    """A fire-and-forget command without a socket raises."""
    client = InvisOutletClient("device.local")
    with pytest.raises(InvisOutletConnectionError):
        await client.restart()


# --- read loop / dispatch -------------------------------------------------


async def test_read_loop_skips_invalid_json(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """Invalid JSON is logged and skipped; the loop keeps reading."""
    client, ws = connected_client
    received: list[SensorData] = []
    client.on_sensor_data(received.append)

    ws._queue.put_nowait(FakeMessage(aiohttp.WSMsgType.TEXT, "{not json"))
    ws.push(
        {
            "payload": {
                "callbackName": CALLBACK_SENSOR_DATA,
                "callbackArgs": [0, {"temp_celsius": 1.0}],
            }
        }
    )
    await asyncio.sleep(0.02)
    assert received and received[0].temperature == 1.0


@pytest.mark.parametrize(
    "msg_type",
    [aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED],
)
async def test_read_loop_breaks_on_control_frames(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
    msg_type: aiohttp.WSMsgType,
) -> None:
    """An error/close frame ends the read loop cleanly."""
    client, ws = connected_client
    ws._queue.put_nowait(FakeMessage(msg_type, ""))
    await asyncio.sleep(0.02)
    assert client._read_task is not None
    assert client._read_task.done()


async def test_read_loop_swallows_unexpected_error(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """An unexpected error inside the loop is caught rather than propagated."""
    client, ws = connected_client
    ws._queue.put_nowait(object())  # accessing .type raises AttributeError
    await asyncio.sleep(0.02)
    assert client._read_task is not None
    assert client._read_task.done()
    assert not client._read_task.cancelled()  # ended via the except, not cancel


async def test_dispatch_isolates_listener_errors(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """One listener raising does not stop the others from running."""
    client, ws = connected_client
    good: list[dict[str, Any]] = []
    client.on_message(CALLBACK_SENSOR_DATA, _raise)
    client.on_message(CALLBACK_SENSOR_DATA, good.append)

    ws.push(
        {"payload": {"callbackName": CALLBACK_SENSOR_DATA, "callbackArgs": [0, {}]}}
    )
    await asyncio.sleep(0.01)
    assert len(good) == 1


async def test_on_message_generic_listener(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """on_message delivers the raw envelope for the given callback id."""
    client, ws = connected_client
    msgs: list[dict[str, Any]] = []
    unsub = client.on_message(CALLBACK_SENSOR_DATA, msgs.append)

    ws.push(
        {"payload": {"callbackName": CALLBACK_SENSOR_DATA, "callbackArgs": [0, {}]}}
    )
    await asyncio.sleep(0.01)
    assert len(msgs) == 1
    unsub()


async def test_on_outlet_status_ignores_empty_args(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """A push with no status list is ignored rather than mis-parsed."""
    client, ws = connected_client
    received: list[OutletStatus] = []
    client.on_outlet_status(received.append)

    ws.push({"payload": {"callbackName": CALLBACK_OUTLET_STATUS, "callbackArgs": []}})
    await asyncio.sleep(0.01)
    assert received == []


# --- on-demand sensor read ------------------------------------------------


async def test_get_sensor_data(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """get_sensor_data parses the wrapped reading, else returns an empty model."""
    client, ws = connected_client
    ws.responses[CALLBACK_SENSOR_DATA] = [0, {"temp_celsius": 22.0}]
    data = await client.get_sensor_data()
    assert data.temperature == 22.0

    ws.responses[CALLBACK_SENSOR_DATA] = []  # malformed / empty
    empty = await client.get_sensor_data()
    assert empty.temperature is None


# --- colour helpers -------------------------------------------------------


async def test_set_color_temperatures_per_led(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """Per-LED temperatures honour the optional states/brightness lists."""
    client, ws = connected_client
    await client.set_color_temperatures(
        LIGHT_NIGHTLIGHT, [3000, 4000], brightness=[50, 60], states=[True, False]
    )
    payload = _last(ws)
    assert payload["callbackName"] == 17
    assert payload["callbackArgs"] == [5, 2, [[1, 50, 3000], [0, 60, 4000]]]


async def test_set_color_pixels_with_brightness(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """set_color_pixels applies a per-LED brightness when given."""
    client, ws = connected_client
    ws.responses[18] = [5, 1, [[1, 40, [27, 35], 4000]]]
    await client.set_color_pixels(LIGHT_NIGHTLIGHT, [(10, 100)], brightness=[77])
    payload = _last(ws)
    assert payload["callbackArgs"] == [5, 1, [[1, 77, [10, 100], 4000]]]


async def test_set_color_effect_pixels(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """set_color_effect_pixels frames the palette plus speed/randomize/level."""
    client, ws = connected_client
    await client.set_color_effect_pixels(
        LIGHT_NIGHTLIGHT,
        [(10, 100), (20, 50)],
        ColorEffect.RAINBOW,
        speed=5,
        randomize=True,
        level=3,
        brightness=[80, 90],
    )
    payload = _last(ws)
    assert payload["callbackName"] == 17
    assert payload["callbackArgs"] == [
        5,
        6,
        [[1, 80, [10, 100]], [1, 90, [20, 50]]],
        5,
        1,
        3,
    ]


# --- sub-device commands --------------------------------------------------


async def test_invisdeco_subdevice_commands(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """restart/reset_invisdeco use callbacks 24 and 25."""
    client, ws = connected_client
    await client.restart_invisdeco()
    assert _last(ws)["callbackName"] == 24
    await client.reset_invisdeco()
    assert _last(ws)["callbackName"] == 25


# --- OTA gating internals -------------------------------------------------


async def test_ota_result_unsubscribe_and_error_isolation(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """A raising result callback is isolated; unsubscribe is idempotent."""
    client, ws = connected_client
    results: list[OtaResult] = []
    unsub = client.on_ota_result(_raise)
    client.on_ota_result(results.append)

    _push_ota(ws, CALLBACK_OTA_RESULT, [1, 1])
    await asyncio.sleep(0.01)
    assert len(results) == 1  # second callback fired despite the first raising

    unsub()
    unsub()  # no-op


async def test_raw_ota_pushes_ignore_malformed_and_unknown(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """Short payloads and unknown device types don't arm the stall machinery."""
    client, ws = connected_client
    _push_ota(ws, CALLBACK_OTA_PROGRESS, [1])  # too short
    _push_ota(ws, CALLBACK_OTA_PROGRESS, [99, 50])  # unknown device_type
    _push_ota(ws, CALLBACK_OTA_RESULT, [1])  # too short
    await asyncio.sleep(0.01)
    assert client._ota_seen_progress == set()
    assert client._ota_stall == {}


# --- firmware check (HTTP) ------------------------------------------------


class _FakeResponse:
    """Async-context-manager stand-in for an aiohttp response."""

    def __init__(self, data: dict[str, Any] | None, error: Exception | None = None) -> None:
        self._data = data
        self._error = error

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    async def json(self, content_type: object = None) -> dict[str, Any] | None:
        return self._data


class _FakeHttpSession:
    """Minimal session exposing the .get() used by check_firmware."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.requested_url: str | None = None

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.requested_url = url
        return self._response

    async def close(self) -> None:
        return None


async def test_check_firmware_success() -> None:
    """A successful lookup returns a populated FirmwareRelease."""
    client = InvisOutletClient("device.local")
    client._session = _FakeHttpSession(  # type: ignore[assignment]
        _FakeResponse(
            {"available_fw_rev": "2.0", "ota_bin_url": "http://x/fw.bin", "message": "notes"}
        )
    )
    release = await client.check_firmware(OtaTarget.INVISOUTLET, "InvisOutlet", "1", "1.0")
    assert release is not None
    assert release.available_fw_rev == "2.0"
    assert release.update_available is True


async def test_check_firmware_variant_overrides_model() -> None:
    """The variant (faceplate type) wins over the model for the product code."""
    session = _FakeHttpSession(
        _FakeResponse({"available_fw_rev": "1.0", "ota_bin_url": "", "message": ""})
    )
    client = InvisOutletClient("device.local")
    client._session = session  # type: ignore[assignment]
    await client.check_firmware(
        OtaTarget.INVISDECO, "InvisDeco", "1", "1.0", variant="Aura"
    )
    assert session.requested_url is not None
    assert "/PM/LIP1/" in session.requested_url  # Aura -> LIP1, not InvisDeco's PRP1


async def test_check_firmware_unknown_model_returns_none() -> None:
    """A model with no known product code has no update channel."""
    client = InvisOutletClient("device.local")
    client._session = _FakeHttpSession(_FakeResponse({}))  # type: ignore[assignment]
    assert (
        await client.check_firmware(OtaTarget.INVISOUTLET, "Mystery", "1", "1.0")
        is None
    )


async def test_check_firmware_not_connected_raises() -> None:
    """Without a session the firmware check cannot run."""
    client = InvisOutletClient("device.local")
    with pytest.raises(InvisOutletConnectionError):
        await client.check_firmware(OtaTarget.INVISOUTLET, "InvisOutlet", "1", "1.0")


async def test_check_firmware_http_error_wrapped() -> None:
    """A transport error surfaces as InvisOutletConnectionError."""
    client = InvisOutletClient("device.local")
    client._session = _FakeHttpSession(  # type: ignore[assignment]
        _FakeResponse(None, error=aiohttp.ClientError("server exploded"))
    )
    with pytest.raises(InvisOutletConnectionError):
        await client.check_firmware(OtaTarget.INVISOUTLET, "InvisOutlet", "1", "1.0")
