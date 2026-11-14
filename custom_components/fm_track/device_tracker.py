"""Device tracker for FM-Track vehicles."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FmTrackConfigEntry
from .entity import FmTrackEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FmTrackConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(FmTrackTracker(coordinator, oid) for oid in coordinator.data)


class FmTrackTracker(FmTrackEntity, TrackerEntity):
    """GPS position of a vehicle."""

    _attr_name = None  # use the device name
    _attr_translation_key = "location"
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator, object_id: str) -> None:
        super().__init__(coordinator, object_id, "location")

    @property
    def latitude(self) -> float | None:
        return self.vehicle.latitude if self.vehicle else None

    @property
    def longitude(self) -> float | None:
        return self.vehicle.longitude if self.vehicle else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        v = self.vehicle
        if not v:
            return {}
        return {
            "speed": v.speed,
            "heading": v.direction,
            "altitude": v.altitude,
            "satellites": v.satellites,
            "last_fix": v.datetime.isoformat() if v.datetime else None,
        }
