"""Diagnostics for FM-Track (privacy-sensitive fields are redacted)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import FmTrackError
from .coordinator import FmTrackConfigEntry

TO_REDACT = {
    CONF_API_KEY,
    "imei",
    "vin",
    "plate_number",
    "latitude",
    "longitude",
    "address",
    "street",
    "house_number",
    "zip",
    "locality",
    "ibutton",
    "first_driver_id",
    "second_driver_id",
    "driver_id",
    "driver_ids",
    "rfid_a",
    "rfid_b",
    "magnetic_card_id",
    "wireless_driver_id",
    "vehicle_id",
    "tco_registration_number",
    "obd_kline_vin_1",
    "obd_kline_vin_2",
    "obd_kline_vin_3",
    "start_address",
    "end_address",
    "start_latitude",
    "start_longitude",
    "end_latitude",
    "end_longitude",
    "lat",
    "lng",
    "lon",
    "iccid",
    "phone_number",
    "sim_number",
    "email",
}


INVENTORY_WINDOW = timedelta(days=30)


async def _input_inventory(c, object_id: str) -> dict[str, Any]:
    """Every input seen in recent history: how often, and the last value.

    Trackers do not send every input in every record (asset trackers often
    report their battery only in heartbeat messages), so this shows what a
    device can deliver beyond the latest record.
    """
    try:
        records = await c.api.async_get_records(object_id, dt_util.utcnow() - INVENTORY_WINDOW, max_pages=10)
    except FmTrackError as err:
        return {"error": str(err)}
    seen: dict[str, dict[str, Any]] = {}

    def note(name: str, key: str, value: Any, when: Any) -> None:
        entry = seen.setdefault(name, {"count": 0, "first_seen": when})
        entry["count"] += 1
        entry["last_seen"] = when
        entry["last"] = "**REDACTED**" if key in TO_REDACT else value

    for record in records:
        when = record.get("datetime")
        for key, value in record.items():
            if key in ("inputs", "position", "object_id", "datetime"):
                continue
            if isinstance(value, dict):
                for sub, sub_value in value.items():
                    note(f"record.{key}.{sub}", sub, sub_value, when)
            else:
                note(f"record.{key}", key, value, when)
        inputs = record.get("inputs") if isinstance(record.get("inputs"), dict) else {}
        for container, values in inputs.items():
            if not isinstance(values, dict):
                note(f"inputs.{container}", container, values, when)
                continue
            for key, value in values.items():
                if container == "tires":
                    continue
                note(f"{container}.{key}", key, value, when)
    return {
        "window_days": INVENTORY_WINDOW.days,
        "records": len(records),
        "first_record": records[0].get("datetime") if records else None,
        "last_record": records[-1].get("datetime") if records else None,
        "triggers": sorted({str(r.get("inputs", {}).get("device_inputs", {}).get("input_trigger")) for r in records}),
        "inputs": dict(sorted(seen.items())),
        "recent_records": records[-10:],
    }


def _redact_scan(probe: dict[str, Any]) -> dict[str, Any]:
    """The v1 scan uses dotted field paths; redact on the last path segment."""
    fields = probe.get("coordinates_v1_scan", {}).get("fields", {})
    for path, entry in fields.items():
        if path.rsplit(".", 1)[-1] in TO_REDACT:
            entry["last"] = "**REDACTED**"
    return probe


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: FmTrackConfigEntry) -> dict[str, Any]:
    c = entry.runtime_data
    vehicles: dict[str, Any] = {}
    for oid, state in (c.data or {}).items():
        last_trip = c.last_trip(oid)
        vehicles[oid] = {
            "name": state.name,
            "fuel_type": state.fuel_type,
            "is_electric": state.is_electric,
            "datetime": state.datetime.isoformat() if state.datetime else None,
            "inputs_datetime": state.inputs_datetime.isoformat() if state.inputs_datetime else None,
            "ignition": state.ignition,
            "active_inputs": sorted(state.active),
            "inactive_inputs": sorted(set(state.values) - state.active),
            "tires": sorted(state.tires),
            "geozone_ids": state.geozone_ids,
            "trips_known": len(c.trips.get(oid, [])),
            "last_trip": vars(last_trip) if last_trip else None,
            "raw_last_coordinate": c.raw_last_coordinate.get(oid),
            "raw_record": c.raw_record.get(oid),
            "raw_stream": c.raw_stream.get(oid),
            "input_inventory": await _input_inventory(c, oid),
            "api_probe": _redact_scan(await c.api.async_probe(oid, dt_util.utcnow() - INVENTORY_WINDOW)),
        }
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "features": c.features,
            "geozone_count": len(c.geozones),
            "stream": {
                "connected": c.stream_connected,
                "messages": c.stream_messages,
                "last_message": c.stream_last_message.isoformat() if c.stream_last_message else None,
            },
            "vehicles": vehicles,
        },
        TO_REDACT,
    )
