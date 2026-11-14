"""Pure parsing helpers for FM-Track API payloads (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Keys that may hold a nested coordinate block in API / stream payloads.
_COORD_CONTAINERS = ("last_coordinate", "coordinate", "position", "location")
# Containers whose children are flattened into VehicleState.values.
_VALUE_CONTAINERS = ("other", "calculated_inputs", "device_inputs")


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp such as 2025-05-01T13:02:00.000Z."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class VehicleState:
    """Last known state of one FM-Track object (vehicle)."""

    object_id: str
    name: str | None = None
    imei: str | None = None
    make: str | None = None
    model: str | None = None
    vin: str | None = None
    plate_number: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    speed: float | None = None
    direction: float | None = None
    altitude: float | None = None
    satellites: int | None = None
    datetime: datetime | None = None
    ignition: str | None = None
    trip_type: str | None = None
    values: dict[str, Any] = field(default_factory=dict)

    def apply(self, update: VehicleState) -> bool:
        """Merge a newer update into this state.

        Returns False (and changes nothing) when the update is not newer than
        what we already have; the stream re-sends the last coordinate after a
        reconnect, so duplicates are expected.
        """
        if (
            update.datetime is not None
            and self.datetime is not None
            and update.datetime <= self.datetime
        ):
            return False
        for attr in (
            "name",
            "imei",
            "make",
            "model",
            "vin",
            "plate_number",
            "latitude",
            "longitude",
            "speed",
            "direction",
            "altitude",
            "satellites",
            "datetime",
            "ignition",
            "trip_type",
        ):
            new = getattr(update, attr)
            if new is not None:
                setattr(self, attr, new)
        self.values.update(update.values)
        return True


def _coordinate_block(data: dict[str, Any]) -> dict[str, Any]:
    for key in _COORD_CONTAINERS:
        block = data.get(key)
        if isinstance(block, dict):
            return block
    return data


def parse_object(data: dict[str, Any]) -> VehicleState | None:
    """Parse an object from /objects, /objects-last-coordinate or the stream."""
    object_id = data.get("object_id") or data.get("id")
    if not object_id:
        return None

    params = data.get("vehicle_params") if isinstance(data.get("vehicle_params"), dict) else {}
    coord = _coordinate_block(data)

    imei = data.get("imei")
    state = VehicleState(
        object_id=str(object_id),
        name=data.get("name") or None,
        imei=str(imei) if imei not in (None, "") else None,
        make=params.get("make") or data.get("make") or None,
        model=params.get("model") or data.get("model") or None,
        vin=params.get("vin") or data.get("vin") or None,
        plate_number=params.get("plate_number") or data.get("plate_number") or None,
        latitude=_num(coord.get("latitude")),
        longitude=_num(coord.get("longitude")),
        speed=_num(coord.get("speed")),
        direction=_num(coord.get("direction")),
        altitude=_num(coord.get("altitude")),
        datetime=parse_datetime(coord.get("datetime") or data.get("datetime")),
        ignition=data.get("ignition_status"),
        trip_type=data.get("trip_type"),
    )
    sats = _num(coord.get("satellites_count"))
    state.satellites = int(sats) if sats is not None else None

    for container in _VALUE_CONTAINERS:
        block = data.get(container)
        if isinstance(block, dict):
            for key, value in block.items():
                if value is not None and not isinstance(value, (dict, list)):
                    state.values[key] = value
    return state


def iter_stream_objects(payload: Any) -> list[dict[str, Any]]:
    """Return the object dicts contained in one SSE data payload."""
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return [p for p in items if isinstance(p, dict)]
        return [payload]
    return []
