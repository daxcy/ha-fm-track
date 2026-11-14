"""Tests for the HA-independent parser (example data from the public API docs)."""

import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("fm_track_parser", ROOT / "custom_components/fm_track/parser.py")
parser = importlib.util.module_from_spec(_spec)
sys.modules["fm_track_parser"] = parser
_spec.loader.exec_module(parser)

FIXTURE = json.loads((ROOT / "tests/fixtures/objects_last_coordinate_v2.json").read_text())


def test_parse_last_coordinate():
    state = parser.parse_object(FIXTURE["results"][0])
    assert state.object_id == "9db8ce84-85ef-11e9-89b6-b33c5b120f33"
    assert state.make == "BMW" and state.model == "R1250"
    assert state.imei == "999955557777"
    assert (state.latitude, state.longitude) == (50.311658, 14.607314)
    assert state.speed == 104 and state.satellites == 13
    assert state.datetime.isoformat() == "2025-05-01T13:02:00+00:00"


def test_parse_without_coordinate():
    state = parser.parse_object(FIXTURE["results"][1])
    assert state.latitude is None and state.make is None


def test_stream_item_and_dedupe():
    base = parser.parse_object(FIXTURE["results"][0])
    payload = {"items": [{
        "object_id": base.object_id,
        "datetime": "2025-05-01T13:05:00.000Z",
        "ignition_status": "OFF",
        "calculated_inputs": {"mileage": 12345.6, "fuel_level": 0},
        "device_inputs": {"can_door_lock_state": "LOCKED"},
    }]}
    [raw] = parser.iter_stream_objects(payload)
    update = parser.parse_object(raw)
    assert base.apply(update) is True
    assert base.ignition == "OFF"
    assert base.values["mileage"] == 12345.6 and base.values["fuel_level"] == 0
    assert base.latitude == 50.311658  # kept from earlier fix
    # same timestamp again (reconnect duplicate) is ignored
    assert base.apply(parser.parse_object(raw)) is False


def test_stream_payload_shapes():
    assert parser.iter_stream_objects([{"object_id": "a"}]) == [{"object_id": "a"}]
    assert parser.iter_stream_objects({"object_id": "a"}) == [{"object_id": "a"}]
    assert parser.iter_stream_objects("x") == []
