"""Tests for the IntecularClient WebSocket client."""

from __future__ import annotations

import asyncio

import pytest

from intecular_client import (
    AccessoryName,
    IntecularClient,
    IntecularCommandError,
    IntecularConnectionError,
    IntecularTimeoutError,
    OtaProgress,
    OtaResult,
    OtaTarget,
    SensorData,
)
from intecular_client.client import (
    CALLBACK_FACTORY_RESET,
    CALLBACK_OTA_PROGRESS,
    CALLBACK_OTA_RESULT,
    CALLBACK_RESET_NETWORK,
    CALLBACK_RESTART,
    CALLBACK_SENSOR_DATA,
)

from .conftest import FakeWebSocket


def _last(ws: FakeWebSocket) -> dict:
    """Return the payload of the most recent request."""
    return ws.sent[-1]["payload"]


async def test_set_outlet_framing(
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """set_outlet should send callbackName 10 with [outlet, 0/1]."""
    client, ws = connected_client
    await client.set_outlet(2, True)
    payload = _last(ws)
    assert payload["callbackName"] == 10
    assert payload["callbackArgs"] == [2, 1]
    assert "packetID" in ws.sent[-1]


async def test_get_config(
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """get_config should parse the nested response into a DeviceConfig."""
    client, ws = connected_client
    ws.responses[1] = {"acc_prefs": {"pmIndicatorBrightness": 60, "capacitiveCtrl": 1}}
    config = await client.get_config()
    assert config.pm_indicator_brightness == 60
    assert config.capacitive_ctrl is True


async def test_set_config_builds_nested_payload(
    connected_client: tuple[IntecularClient, FakeWebSocket],
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
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """get_device_info should parse IM and inject host/port."""
    client, ws = connected_client
    ws.responses[12] = {"IM": {"sn": "S1", "MAC": "aa", "device": "InvisOutlet"}}
    info = await client.get_device_info()
    assert info.serial_number == "S1"
    assert info.host == "device.local"
    assert info.port == 80


async def test_accessory_names_round_trip(
    connected_client: tuple[IntecularClient, FakeWebSocket],
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
    connected_client: tuple[IntecularClient, FakeWebSocket],
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
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """get_outlet_status should parse the positional array."""
    client, ws = connected_client
    ws.responses[9] = [1, 0]
    status = await client.get_outlet_status()
    assert status.is_on(1) is True
    assert status.is_on(2) is False


async def test_nightlight(
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """set/get nightlight should use [mode, brightness]."""
    client, ws = connected_client
    await client.set_nightlight(1, 75)
    assert _last(ws)["callbackArgs"] == [1, 75]

    ws.responses[15] = [1, 75]
    state = await client.get_nightlight()
    assert state.mode == 1
    assert state.brightness == 75


async def test_nightlight_temperature_and_get(
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """set_nightlight_temperature (17) and get_nightlight_color (18)."""
    client, ws = connected_client
    await client.set_nightlight_temperature(3500, brightness=90)
    payload = _last(ws)
    assert payload["callbackName"] == 17
    assert payload["callbackArgs"] == [5, 2, [[1, 90, 3500]]]

    ws.responses[18] = [5, 2, [[1, 100, [200, 50], 4000]]]
    state = await client.get_nightlight_color()
    assert state.leds[0].hue == 200
    assert state.leds[0].temperature == 4000


async def test_set_nightlight_color(
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """set_nightlight_color (17) should frame as mode 1 with [[state, bri, [hue, sat]]]."""
    client, ws = connected_client
    await client.set_nightlight_color(200, 80, brightness=90)
    payload = _last(ws)
    assert payload["callbackName"] == 17
    assert payload["callbackArgs"] == [5, 1, [[1, 90, [200, 80]]]]


async def test_get_nightlight_color_missing_raises(
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """get_nightlight_color raises a clear error when no light data comes back."""
    client, ws = connected_client
    ws.responses[18] = []  # device returns nothing (e.g. no Aura attached)
    with pytest.raises(IntecularCommandError):
        await client.get_nightlight_color()


async def test_available_updates(
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """get_available_updates should parse the IM/PM revisions."""
    client, ws = connected_client
    ws.responses[20] = {"IM": {"fw_rev": "1.0", "available_fw_rev": "1.1"}}
    updates = await client.get_available_updates()
    assert updates.update_available is True


async def test_perform_ota_update_framing(
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """perform_ota_update should send [target, method]."""
    client, ws = connected_client
    ws.responses[21] = [1, 1]
    await client.perform_ota_update(OtaTarget.INVISDECO, 0)
    assert _last(ws)["callbackArgs"] == [1, 0]


async def test_calibrate_temp_humidity_converts_to_millis(
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """Calibration values should be sent in milli-units."""
    client, ws = connected_client
    await client.calibrate_temp_humidity(25.0, 50.0)
    assert _last(ws)["callbackArgs"] == [25000, 50000]


async def test_calibrate_occupancy(
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """Occupancy calibration should send [durationSeconds]."""
    client, ws = connected_client
    await client.calibrate_occupancy(30)
    assert _last(ws)["callbackArgs"] == [30]


async def test_puback_failure_raises(
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """A PUBACK of 0 should raise IntecularCommandError."""
    client, ws = connected_client
    ws.puback = 0
    with pytest.raises(IntecularCommandError):
        await client.set_outlet(1, True)


async def test_timeout_raises(
    connected_client: tuple[IntecularClient, FakeWebSocket],
) -> None:
    """A response that never arrives should raise IntecularTimeoutError."""
    client, ws = connected_client
    ws.no_reply.add(9)  # callback that normally expects a reply
    with pytest.raises(IntecularTimeoutError):
        await client.get_outlet_status(timeout=0.05)


async def test_not_connected_raises() -> None:
    """Sending without a connection should raise IntecularConnectionError."""
    client = IntecularClient("device.local")
    with pytest.raises(IntecularConnectionError):
        await client.set_outlet(1, True)


async def test_sensor_data_push_dispatch(
    connected_client: tuple[IntecularClient, FakeWebSocket],
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


async def test_ota_push_dispatch(
    connected_client: tuple[IntecularClient, FakeWebSocket],
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
            "payload": {"callbackName": CALLBACK_OTA_PROGRESS, "callbackArgs": [0, 1, 55]},
        }
    )
    ws.push(
        {
            "packetID": 2,
            "payload": {"callbackName": CALLBACK_OTA_RESULT, "callbackArgs": [0, 1, 1]},
        }
    )
    await asyncio.sleep(0.01)
    assert progress[0].progress == 55
    assert results[0].success is True
