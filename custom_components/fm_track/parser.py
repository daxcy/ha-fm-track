"""Pure parsing helpers for FM-Track API payloads (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Containers whose children are flattened into VehicleState.values.
VALUE_CONTAINERS = ("other", "calculated_inputs", "device_inputs")
# Calculated inputs are reported as 0.00 when they are not configured on the
# platform, so they only count once a non-zero value has been seen.
CALCULATED = "calculated_inputs"

ELECTRIC_FUEL_TYPES = {"ELECTRIC", "ELECTRICITY", "EV", "BEV"}


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp such as 2025-05-01T13:02:00.000Z."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_float(value: Any) -> float | None:
    """Convert numbers and numeric strings; everything else becomes None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def format_address(address: Any) -> str | None:
    """Turn an API Address object into a single readable line."""
    if not isinstance(address, dict):
        return None
    street = " ".join(p for p in (address.get("street"), address.get("house_number")) if p)
    town = " ".join(p for p in (address.get("zip"), address.get("locality")) if p)
    parts = [p for p in (street, town, address.get("country")) if p]
    return ", ".join(parts) or None


@dataclass
class VehicleState:
    """Last known state of one FM-Track object (vehicle or asset)."""

    object_id: str
    name: str | None = None
    imei: str | None = None
    make: str | None = None
    model: str | None = None
    vin: str | None = None
    plate_number: str | None = None
    fuel_type: str | None = None
    fuel_tank_capacity: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    speed: float | None = None
    direction: float | None = None
    altitude: float | None = None
    satellites: int | None = None
    datetime: datetime | None = None
    datetime_raw: str | None = None
    ignition: str | None = None
    trip_type: str | None = None
    geozone_ids: list[str] | None = None
    values: dict[str, Any] = field(default_factory=dict)
    # Keys in `values` that carry real data (see CALCULATED above).
    active: set[str] = field(default_factory=set)
    tires: dict[str, dict[str, float]] = field(default_factory=dict)
    # True when this record carried an inputs block (history record / stream).
    has_inputs: bool = False
    # Timestamp of the record whose inputs we hold; differs from `datetime`
    # when only a newer position (without inputs) is known.
    inputs_datetime: datetime | None = None

    @property
    def is_electric(self) -> bool:
        if self.fuel_type and self.fuel_type.upper() in ELECTRIC_FUEL_TYPES:
            return True
        return bool({"canbus_battery_power", "canbus_distance_until_recharge", "state_of_charge"} & self.active)

    def get(self, key: str) -> Any:
        """Value of an input, or None when it was never really reported."""
        return self.values.get(key) if key in self.active else None

    def apply(self, update: VehicleState) -> bool:
        """Merge an update into this state.

        Older records are ignored. A record with the same timestamp is merged
        only when it adds inputs we did not have yet (the last-coordinate API
        has no inputs; the full record for that timestamp does). The stream
        re-sends the last record after a reconnect, which is then a no-op.
        """
        if update.datetime is not None and self.datetime is not None:
            if update.datetime < self.datetime:
                return False
            if update.datetime == self.datetime and (
                not update.has_inputs or self.inputs_datetime == update.datetime
            ):
                return False
        for attr in (
            "name",
            "imei",
            "make",
            "model",
            "vin",
            "plate_number",
            "fuel_type",
            "fuel_tank_capacity",
            "latitude",
            "longitude",
            "speed",
            "direction",
            "altitude",
            "satellites",
            "datetime",
            "datetime_raw",
            "ignition",
            "trip_type",
            "geozone_ids",
        ):
            new = getattr(update, attr)
            if new is not None:
                setattr(self, attr, new)
        if update.has_inputs:
            self.has_inputs = True
            self.inputs_datetime = update.datetime
        self.values.update(update.values)
        self.active |= update.active
        for tire, data in update.tires.items():
            self.tires.setdefault(tire, {}).update(data)
        return True


def backfill(state: VehicleState, older: list[VehicleState]) -> int:
    """Fill inputs the latest record lacks with their last known value.

    Devices do not send every input in every message; asset trackers for
    example report their battery only in occasional heartbeats. `older`
    must be sorted oldest first. Returns the number of inputs added.
    """
    found: dict[str, Any] = {}
    for record in older:
        for key in record.active:
            found[key] = record.values[key]
    added = 0
    for key, value in found.items():
        if key not in state.active:
            state.values[key] = value
            state.active.add(key)
            added += 1
    return added


def _not_available(key: str, value: Any) -> bool:
    """Sentinel values devices send for "not available" (e.g. -272.66 °C)."""
    if isinstance(value, str) and value.upper() in ("NOT_AVAILABLE", "UNKNOWN"):
        return True
    if "temp" in key:
        num = to_float(value)
        return num is not None and (num < -60 or num > 250)
    return False


def _flatten_inputs(state: VehicleState, block: dict[str, Any]) -> None:
    for container in VALUE_CONTAINERS:
        values = block.get(container)
        if not isinstance(values, dict):
            continue
        state.has_inputs = True
        for key, value in values.items():
            if value is None or isinstance(value, (dict, list)):
                continue
            state.values[key] = value
            if _not_available(key, value):
                continue
            if container != CALCULATED or (to_float(value) or 0) != 0:
                state.active.add(key)
    tires = block.get("tires")
    if isinstance(tires, dict):
        for tire, data in tires.items():
            if not isinstance(data, dict):
                continue
            parsed = {k: f for k, v in data.items() if (f := to_float(v)) is not None}
            if parsed:
                state.tires[str(tire)] = parsed


def parse_object(data: dict[str, Any]) -> VehicleState | None:
    """Parse an object from /objects-last-coordinate, a history record or the stream."""
    object_id = data.get("object_id") or data.get("id")
    if not object_id:
        return None

    params = data.get("vehicle_params") if isinstance(data.get("vehicle_params"), dict) else {}
    coord: dict[str, Any] = data
    for key in ("last_coordinate", "position", "coordinate", "location"):
        if isinstance(data.get(key), dict):
            coord = data[key]
            break

    dt_raw = coord.get("datetime") or data.get("datetime")
    imei = data.get("imei")
    sats = to_float(coord.get("satellites_count"))
    trip_type = data.get("trip_type") or data.get("business_or_private")
    state = VehicleState(
        object_id=str(object_id),
        name=data.get("name") or None,
        imei=str(imei) if imei not in (None, "") else None,
        make=params.get("make") or None,
        model=params.get("model") or None,
        vin=params.get("vin") or None,
        plate_number=params.get("plate_number") or None,
        fuel_type=params.get("fuel_type") or None,
        fuel_tank_capacity=to_float(params.get("fuel_tank_capacity")),
        latitude=to_float(coord.get("latitude")),
        longitude=to_float(coord.get("longitude")),
        speed=to_float(coord.get("speed")),
        direction=to_float(coord.get("direction")),
        altitude=to_float(coord.get("altitude")),
        satellites=int(sats) if sats is not None else None,
        datetime=parse_datetime(dt_raw),
        datetime_raw=dt_raw if isinstance(dt_raw, str) else None,
        ignition=data.get("ignition_status") or None,
        trip_type=trip_type or None,
    )
    if isinstance(data.get("geozone_ids"), list):
        state.geozone_ids = [str(g) for g in data["geozone_ids"]]

    # Current API: everything below "inputs"; older payloads had the
    # containers at the top level.
    if isinstance(data.get("inputs"), dict):
        _flatten_inputs(state, data["inputs"])
        if state.geozone_ids is None and isinstance(data["inputs"].get("geozone_ids"), list):
            state.geozone_ids = [str(g) for g in data["inputs"]["geozone_ids"]]
    _flatten_inputs(state, data)
    if state.has_inputs:
        state.inputs_datetime = state.datetime
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


@dataclass
class Trip:
    """One finished trip from the Trips API."""

    object_id: str
    start: datetime | None
    end: datetime | None
    distance: float | None
    duration: int | None
    fuel: float | None
    trip_type: str | None
    start_address: str | None
    end_address: str | None
    start_latitude: float | None = None
    start_longitude: float | None = None
    end_latitude: float | None = None
    end_longitude: float | None = None

    @property
    def key(self) -> str:
        return f"{self.object_id}:{self.start.isoformat() if self.start else '?'}"


def _metres_to_km(value: Any) -> float | None:
    metres = to_float(value)
    return None if metres is None else round(metres / 1000, 2)


def parse_trip(data: dict[str, Any]) -> Trip | None:
    if not isinstance(data, dict):
        return None
    start = data.get("trip_start") if isinstance(data.get("trip_start"), dict) else {}
    end = data.get("trip_end") if isinstance(data.get("trip_end"), dict) else {}
    duration = to_float(data.get("trip_duration"))
    start_dt = parse_datetime(start.get("datetime"))
    end_dt = parse_datetime(end.get("datetime"))
    if start_dt is None and end_dt is None:
        return None
    return Trip(
        object_id=str(data.get("object_id") or ""),
        start=start_dt,
        end=end_dt,
        # The Trips API reports the trip distance in metres.
        distance=_metres_to_km(data.get("mileage")),
        duration=int(duration) if duration is not None else None,
        fuel=to_float(data.get("total_fuel_consumption")),
        trip_type=data.get("trip_type"),
        start_address=format_address(start.get("address")),
        end_address=format_address(end.get("address")),
        start_latitude=to_float(start.get("latitude")),
        start_longitude=to_float(start.get("longitude")),
        end_latitude=to_float(end.get("latitude")),
        end_longitude=to_float(end.get("longitude")),
    )


# Li-ion open-circuit voltage → state of charge (rough, resting cell).
_LIION_CURVE = (
    (4.20, 100),
    (4.10, 90),
    (4.00, 80),
    (3.90, 65),
    (3.80, 50),
    (3.70, 35),
    (3.60, 20),
    (3.50, 10),
    (3.40, 5),
    (3.30, 0),
)


def estimate_liion_percent(voltage: Any) -> int | None:
    """Estimate a single-cell Li-ion battery percentage from its voltage."""
    volts = to_float(voltage)
    if volts is None or volts <= 0:
        return None
    if volts > 100:  # reported in millivolts
        volts /= 1000
    if volts > 4.5 or volts < 2.5:  # not a single Li-ion cell
        return None
    if volts >= _LIION_CURVE[0][0]:
        return 100
    for (v_hi, p_hi), (v_lo, p_lo) in zip(_LIION_CURVE, _LIION_CURVE[1:]):
        if volts >= v_lo:
            return round(p_lo + (p_hi - p_lo) * (volts - v_lo) / (v_hi - v_lo))
    return 0
