"""Tests for the data models and wire-format mapping."""

from __future__ import annotations

from invisoutlet.models import (
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


def test_device_config_to_raw_omits_none_and_nests() -> None:
    """to_raw should nest by wire path, coerce bools, and drop None."""
    config = DeviceConfig(
        outlet_power_indicator_on=False,
        pm_indicator_brightness=50,
        mqtt_enabled=True,
        mqtt_qos=1,
        home_away_enabled=True,
        home_away_min_brightness=10,
    )
    raw = config.to_raw()
    assert raw == {
        "acc_prefs": {
            "outletPwrIndicatorOn": 0,
            "pmIndicatorBrightness": 50,
            "homeAwayMode": {"enabled": 1, "minBrightness": 10},
        },
        "sys_prefs": {"mqtt": {"enabled": 1, "qos": 1}},
    }


def test_device_config_round_trip() -> None:
    """from_raw should invert to_raw for set fields."""
    config = DeviceConfig(
        capacitive_ctrl=True,
        adaptive_min_brightness=5,
        mqtt_broker_url="mqtt://broker",
    )
    parsed = DeviceConfig.from_raw(config.to_raw())
    assert parsed.capacitive_ctrl is True
    assert parsed.adaptive_min_brightness == 5
    assert parsed.mqtt_broker_url == "mqtt://broker"
    assert parsed.motion_away_feature is None


def test_device_config_parses_readonly_internet() -> None:
    """Read-only network info should parse from sys_prefs.internet."""
    raw = {"sys_prefs": {"internet": {"ip": "10.0.0.5", "mainDNS": "1.1.1.1"}}}
    config = DeviceConfig.from_raw(raw)
    assert config.internet_ip == "10.0.0.5"
    assert config.internet_main_dns == "1.1.1.1"
    assert config.internet_backup_dns is None


def test_sensor_data_from_raw() -> None:
    """SensorData should map every documented key, including new ones."""
    data = SensorData.from_raw(
        {
            "temp_celsius": "21.5",
            "humidity": 40,
            "AQI": 75,
            "AQI_accuracy": 3,
            "temphumidity_accuracy": 1,
            "co2_equiv": 600,
            "co2_peak_lvl": 900,
            "co2_accuracy": 2,
            "bvoc_equiv": "0.5",
            "bvoc_accuracy": 1,
            "pressure": 101325,
            "lux": "120.0",
            "distance": 150,
            "occupancy_state": 1,
            "movement_energy": 0,
            "stationary_energy": 30,
            "gas": 50000,
            "BME680_temp_celsius": "22.0",
            "BME680_humidity": "41.0",
            "temp_valid": True,
            "aqi_valid": 1,
            "lux_valid": 0,
            "occupancy_valid": True,
        }
    )
    assert data.temperature == 21.5
    assert data.air_quality_index == 75
    assert data.aqi_accuracy == 3
    assert data.temp_humidity_accuracy == 1
    assert data.co2_peak == 900
    assert data.voc == 0.5
    assert data.bme680_temperature == 22.0
    assert data.temp_valid is True
    assert data.aqi_valid is True
    assert data.lux_valid is False
    assert data.occupancy is True
    assert data.motion is False


def test_sensor_data_minimal_variant() -> None:
    """Missing keys should stay None rather than raising."""
    data = SensorData.from_raw({"lux_valid": True, "lux": 5})
    assert data.illuminance == 5.0
    assert data.lux_valid is True
    assert data.temperature is None
    assert data.occupancy is None
    assert data.motion is None


def test_device_info_from_raw_with_radar() -> None:
    """DeviceInfo should parse IM and PM (including radar) blocks."""
    info = DeviceInfo.from_raw(
        {
            "IM": {"sn": "IM123", "MAC": "aa:bb", "device": "InvisOutlet", "fw_rev": "1.2"},
            "PM": {
                "sn": "PM456",
                "MAC": "cc:dd",
                "device": "InvisDeco",
                "type": "deco",
                "online": True,
                "radar": {"fw_ver": "3.0", "hw_type": "R1", "MAC": "ee:ff"},
            },
        },
        host="10.0.0.5",
        port=3333,
    )
    assert info.serial_number == "IM123"
    assert info.host == "10.0.0.5"
    assert info.sub_device is not None
    assert info.sub_device.serial_number == "PM456"
    assert info.sub_device.online is True
    assert info.sub_device.radar_fw_ver == "3.0"
    assert info.sub_device.radar_mac == "ee:ff"


def test_device_info_no_sub_device() -> None:
    """No PM block means no sub-device."""
    info = DeviceInfo.from_raw({"IM": {"sn": "IM123", "MAC": "aa", "device": "x"}})
    assert info.sub_device is None


def test_accessory_name_round_trip() -> None:
    """AccessoryName should convert both directions."""
    name = AccessoryName.from_raw({"accessory": 1, "name": "Outlet 1"})
    assert name == AccessoryName(accessory=1, name="Outlet 1")
    assert name.to_raw() == {"accessory": 1, "name": "Outlet 1"}


def test_outlet_status() -> None:
    """OutletStatus should expose per-outlet state, 1-indexed."""
    status = OutletStatus.from_raw([1, 0])
    assert status.outlets == [True, False]
    assert status.is_on(1) is True
    assert status.is_on(2) is False


def test_nightlight_state_round_trip() -> None:
    """NightlightState should convert both directions and report on/off."""
    state = NightlightState.from_raw([1, 100])
    assert state == NightlightState(mode=1, brightness=100)
    assert state.on is True
    assert state.to_raw() == [1, 100]
    assert NightlightState.from_raw([0, 0]).on is False


def test_color_light_state_parse_and_serialize() -> None:
    """ColorLightState should parse callback 18 and serialize callback 17."""
    state = ColorLightState.from_raw([5, 2, [[1, 100, [360, 100], 4000]]])
    assert state.light == 5
    assert state.mode == 2
    assert len(state.leds) == 1
    led = state.leds[0]
    assert led.state is True
    assert led.brightness == 100
    assert led.hue == 360
    assert led.saturation == 100
    assert led.temperature == 4000

    out = ColorLightState(
        light=5,
        mode=2,
        leds=[ColorLedEntry(state=True, brightness=80, temperature=3000)],
    )
    assert out.to_temperature_raw() == [5, 2, [[1, 80, 3000]]]


def test_color_light_state_to_hsv_raw() -> None:
    """ColorLightState should serialize HSV as [light, mode, [[state, bri, [hue, sat]]]]."""
    out = ColorLightState(
        light=5,
        mode=1,
        leds=[ColorLedEntry(state=True, brightness=80, hue=200, saturation=60)],
    )
    assert out.to_hsv_raw() == [5, 1, [[1, 80, [200, 60]]]]


def test_available_updates() -> None:
    """AvailableUpdates should detect when a newer revision exists."""
    updates = AvailableUpdates.from_raw(
        {
            "IM": {"fw_rev": "1.0", "available_fw_rev": "1.1"},
            "PM": {"fw_rev": "2.0", "available_fw_rev": "2.0"},
        }
    )
    assert updates.im.update_available is True
    assert updates.pm is not None
    assert updates.pm.update_available is False
    assert updates.update_available is True


def test_available_updates_no_pm() -> None:
    """A response without PM should leave pm as None."""
    updates = AvailableUpdates.from_raw({"IM": {"fw_rev": "1.0", "available_fw_rev": "1.0"}})
    assert updates.pm is None
    assert updates.update_available is False


def test_ota_progress_and_result() -> None:
    """OTA push payloads parse [device_type, value] (callbacks 22/23)."""
    progress = OtaProgress.from_raw([1, 42])
    assert progress.device_type == 1
    assert progress.progress == 42

    result = OtaResult.from_raw([2, 1])
    assert result.device_type == 2
    assert result.success is True
    assert OtaResult.from_raw([2, 0]).success is False
