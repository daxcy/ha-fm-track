"""Set up the integration inside a real Home Assistant test instance with a mocked API."""

import json
import pathlib
import re
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.fm_track.const import DOMAIN
from custom_components.fm_track.diagnostics import async_get_config_entry_diagnostics

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"
BASE = "https://api.fm-track.com"


def _last_coordinate() -> dict:
    data = json.loads((FIXTURES / "objects_last_coordinate_v2.json").read_text())
    car = data["results"][0]
    car.update(id="abc123", name="Test car")
    car["vehicle_params"]["fuel_type"] = "ELECTRIC"
    return {"results": [car]}


def _record() -> dict:
    return json.loads((FIXTURES / "history_record_v2.json").read_text())


def _trips() -> dict:
    end = dt_util.utcnow() - timedelta(minutes=30)
    start = end - timedelta(minutes=21)
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {
        "trips": [
            {
                "object_id": "abc123",
                "mileage": 12400,
                "trip_duration": 1260,
                "trip_type": "PRIVATE",
                "trip_start": {"datetime": fmt(start), "address": {"locality": "Eindhoven"}},
                "trip_end": {"datetime": fmt(end), "address": {"street": "Markt", "locality": "Helmond"}},
            }
        ]
    }


def _mock_api(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/objects-last-coordinate", json=_last_coordinate())
    aioclient_mock.get(re.compile(r".*/objects/abc123/coordinates/.*"), json=_record())
    aioclient_mock.get(re.compile(r".*/objects/abc123/coordinates(\?.*)?$"), json={"items": [_record()]})
    aioclient_mock.get(re.compile(r".*/objects/abc123/trips.*"), json=_trips())
    aioclient_mock.get(f"{BASE}/geozones", json={"items": [{"id": "0d5d7bc2", "name": "Thuis"}]})
    aioclient_mock.get(f"{BASE}/detected-events", json={"events": []})
    aioclient_mock.get(f"{BASE}/object-coordinates-stream", status=403)


async def _setup(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> MockConfigEntry:
    _mock_api(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"api_key": "secret", "base_url": BASE, "vehicles": ["abc123"]},
        unique_id="test",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_creates_entities(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    await _setup(hass, aioclient_mock)

    def state(entity_id: str) -> str:
        st = hass.states.get(entity_id)
        assert st is not None, f"{entity_id} missing; have: {sorted(hass.states.async_entity_ids())}"
        return st.state

    assert state("device_tracker.test_car") == "not_home"
    assert state("sensor.test_car_battery") == "78.0"
    assert state("sensor.test_car_range") == "312.0"
    assert state("sensor.test_car_odometer") == "15234.5"
    assert state("sensor.test_car_tracker_battery") == "85"
    assert state("sensor.test_car_supply_voltage") == "12.6"
    assert state("sensor.test_car_geozone") == "Thuis"
    assert state("sensor.test_car_last_trip_distance") == "12.4"
    assert state("sensor.test_car_last_trip_destination") == "Markt, Helmond"
    assert state("sensor.test_car_tyre_1_pressure") == "250.0"
    assert state("binary_sensor.test_car_charging") == "off"
    assert state("binary_sensor.test_car_door_lock") == "off"
    assert state("binary_sensor.test_car_ignition") == "off"
    assert state("binary_sensor.test_car_moving") == "off"
    assert state("binary_sensor.fm_track_live_stream") == "off"
    # electric car: no fuel sensors, and calculated inputs that are 0 are ignored
    assert hass.states.get("sensor.test_car_fuel_level") is None
    assert hass.states.get("sensor.test_car_custom_input_1") is None
    # windows and sunroof are not in this fixture
    assert hass.states.get("binary_sensor.test_car_sunroof") is None


async def test_diagnostics_redacts(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    entry = await _setup(hass, aioclient_mock)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diag, default=str)
    assert "secret" not in text
    assert "50.311658" not in text and "999955557777" not in text
    vehicle = diag["vehicles"]["abc123"]
    assert "canbus_battery_power" in vehicle["active_inputs"]
    inventory = vehicle["input_inventory"]
    assert inventory["records"] == 1
    assert inventory["inputs"]["device_inputs.canbus_battery_power"]["count"] == 1
    assert diag["features"]["stream"] is False or diag["features"]["stream"] is None
