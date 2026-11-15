"""Tests for the HA-independent parser (example data based on the public API docs)."""

import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("fm_track_parser", ROOT / "custom_components/fm_track/parser.py")
parser = importlib.util.module_from_spec(_spec)
sys.modules["fm_track_parser"] = parser
_spec.loader.exec_module(parser)

FIXTURES = ROOT / "tests/fixtures"
LAST = json.loads((FIXTURES / "objects_last_coordinate_v2.json").read_text())
RECORD = json.loads((FIXTURES / "history_record_v2.json").read_text())


def test_parse_last_coordinate():
    state = parser.parse_object(LAST["results"][0])
    assert state.object_id == "9db8ce84-85ef-11e9-89b6-b33c5b120f33"
    assert state.make == "BMW" and state.model == "R1250" and state.fuel_type == "DIESEL"
    assert state.imei == "999955557777"
    assert (state.latitude, state.longitude) == (50.311658, 14.607314)
    assert state.speed == 104 and state.satellites == 13
    assert state.datetime.isoformat() == "2025-05-01T13:02:00+00:00"
    assert state.datetime_raw == "2025-05-01T13:02:00.000Z"
    assert not state.has_inputs and state.inputs_datetime is None


def test_parse_without_coordinate():
    state = parser.parse_object(LAST["results"][1])
    assert state.latitude is None and state.make is None


def test_nested_inputs_and_calculated_zeros():
    rec = parser.parse_object(RECORD)
    assert rec.has_inputs and rec.inputs_datetime == rec.datetime
    assert rec.get("canbus_battery_power") == 78
    assert rec.get("mileage") == 15234.5
    # calculated inputs that are 0.00 are "not configured"
    assert rec.get("fuel_level") is None and rec.get("custom_input_1") is None
    assert "fuel_level" in rec.values
    assert rec.get("virtual_gps_odometer") == 741.33
    assert rec.is_electric
    assert rec.geozone_ids == ["0d5d7bc2"]
    assert rec.tires["tire01"]["tire_pressure"] == 250.0
    assert rec.trip_type == "PRIVATE" and rec.ignition == "OFF"


def test_record_enriches_same_timestamp():
    base = parser.parse_object({**LAST["results"][0], "id": "abc123"})
    rec = parser.parse_object(RECORD)
    assert base.apply(rec) is True
    assert base.get("canbus_battery_power") == 78 and base.inputs_datetime == base.datetime
    # same record again is a no-op
    assert base.apply(parser.parse_object(RECORD)) is False
    # a newer position without inputs is accepted and keeps old inputs
    newer = parser.parse_object({**LAST["results"][0], "id": "abc123",
                                 "last_coordinate": {**LAST["results"][0]["last_coordinate"],
                                                     "datetime": "2025-05-01T13:10:00.000Z"}})
    assert base.apply(newer) is True
    assert base.inputs_datetime != base.datetime and base.get("canbus_battery_power") == 78


def test_stream_payload_shapes():
    assert parser.iter_stream_objects({"items": [RECORD]}) == [RECORD]
    assert parser.iter_stream_objects([{"object_id": "a"}]) == [{"object_id": "a"}]
    assert parser.iter_stream_objects({"object_id": "a"}) == [{"object_id": "a"}]
    assert parser.iter_stream_objects("x") == []


def test_trip_parsing():
    trip = parser.parse_trip({
        "object_id": "abc123", "mileage": 12400, "trip_duration": 1260, "trip_type": "PRIVATE",
        "trip_start": {"datetime": "2025-05-01T12:00:00.000Z",
                       "address": {"street": "Dorpsstraat", "house_number": "1", "zip": "1234 AB",
                                   "locality": "Ergens", "country": "Nederland"}},
        "trip_end": {"datetime": "2025-05-01T12:21:00.000Z", "address": {"locality": "Elders"}},
    })
    assert trip.distance == 12.4 and trip.duration == 1260
    assert trip.start_address == "Dorpsstraat 1, 1234 AB Ergens, Nederland"
    assert trip.end_address == "Elders"
    assert parser.parse_trip({"mileage": 1}) is None


def test_not_available_values_and_soc():
    rec = parser.parse_object({
        "object_id": "x", "datetime": "2026-11-15T07:35:29.000Z",
        "inputs": {
            "device_inputs": {"canbus_ambient_air_temperature": -272.66, "can_door_lock_state": "NOT_AVAILABLE",
                              "gnss_antenna": "UNKNOWN", "pcb_temperature": 5},
            "calculated_inputs": {"state_of_charge": 96, "fuel_level": 0},
        },
    })
    assert rec.get("canbus_ambient_air_temperature") is None
    assert rec.get("can_door_lock_state") is None and rec.get("gnss_antenna") is None
    assert rec.get("pcb_temperature") == 5
    assert rec.get("state_of_charge") == 96 and rec.is_electric


def test_liion_estimate():
    assert parser.estimate_liion_percent(4.25) == 100
    assert parser.estimate_liion_percent(4.05) == 85
    assert parser.estimate_liion_percent(3700) == 35  # millivolts
    assert parser.estimate_liion_percent(3.2) == 0
    assert parser.estimate_liion_percent(12.6) is None  # not a Li-ion cell
    assert parser.estimate_liion_percent(None) is None
