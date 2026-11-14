"""Diagnostics for FM-Track (privacy-sensitive fields are redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

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
}


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
