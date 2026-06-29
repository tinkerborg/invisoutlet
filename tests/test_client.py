"""Tests for the InvisOutletClient WebSocket client."""

from __future__ import annotations

import asyncio

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
)

from .conftest import FakeSession, FakeWebSocket


def _last(ws: FakeWebSocket) -> dict:
    """Return the payload of the most recent request."""
    return ws.sent[-1]["payload"]


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


async def test_set_color_effect(
    connected_client: tuple[InvisOutletClient, FakeWebSocket],
) -> None:
    """set_color_effect round-trips the full frame: read, switch mode, recolour."""
    client, ws = connected_client
    # Device's current full frame (2 LEDs + undocumented trailing fields).
    ws.responses[18] = [5, 1, [[1, 40, [27, 35], 4000]] * 2, 1, 0, 40]
    await client.set_color_effect(
        LIGHT_NIGHTLIGHT, ColorEffect.RAINBOW, hue=200, saturation=80, brightness=90
    )
    payload = _last(ws)
    assert payload["callbackName"] == 17
    # mode -> 6, LEDs recoloured/dimmed, kelvin + trailing fields preserved.
    assert payload["callbackArgs"] == [
        5,
        6,
        [[1, 90, [200, 80], 4000], [1, 90, [200, 80], 4000]],
        1,
        0,
        40,
    ]


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
