"""Device tracker for FM-Track vehicles."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FmTrackConfigEntry, FmTrackCoordinator
from .entity import FmTrackEntity
from .parser import estimate_liion_percent, to_float


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FmTrackConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    added: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [FmTrackTracker(coordinator, oid) for oid in (coordinator.data or {}) if oid not in added]
        added.update(t._object_id for t in new)
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class FmTrackTracker(FmTrackEntity, TrackerEntity):
    """GPS position of a vehicle or asset."""

    _attr_name = None  # use the device name
    _attr_translation_key = "location"
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: FmTrackCoordinator, object_id: str) -> None:
        super().__init__(coordinator, object_id, "location")

    @property
    def latitude(self) -> float | None:
        return self.vehicle.latitude if self.vehicle else None

    @property
    def longitude(self) -> float | None:
        return self.vehicle.longitude if self.vehicle else None

    @property
    def location_accuracy(self) -> float:
        # Rough horizontal accuracy from HDOP (≈ 5 m per HDOP unit).
        hdop = to_float(self.vehicle.get("hdop")) if self.vehicle else None
        return round(hdop * 5, 1) if hdop else 0

    @property
    def battery_level(self) -> int | None:
        """Battery of the tracker itself (asset trackers), not the car's EV battery."""
        v = self.vehicle
        return estimate_liion_percent(v.get("battery_voltage")) if v else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        v = self.vehicle
        if not v:
            return {}
        attrs: dict[str, Any] = {
            "speed": v.speed,
            "heading": v.direction,
            "altitude": v.altitude,
            "satellites": v.satellites,
            "ignition": v.ignition,
            "last_fix": v.datetime.isoformat() if v.datetime else None,
        }
        if v.geozone_ids is not None:
            attrs["geozones"] = [self.coordinator.geozones.get(g, g) for g in v.geozone_ids]
        if v.plate_number:
            attrs["plate_number"] = v.plate_number
        return attrs
