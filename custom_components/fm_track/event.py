"""Event entity per vehicle: ignition on/off, trip ended, platform events."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPES
from .coordinator import FmTrackConfigEntry, FmTrackCoordinator
from .entity import FmTrackEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FmTrackConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    added: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [FmTrackEvent(coordinator, oid) for oid in (coordinator.data or {}) if oid not in added]
        added.update(e._object_id for e in new)
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class FmTrackEvent(FmTrackEntity, EventEntity):
    _attr_translation_key = "vehicle_event"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: FmTrackCoordinator, object_id: str) -> None:
        super().__init__(coordinator, object_id, "event")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_event_listener(self._object_id, self._handle_vehicle_event)
        )

    @callback
    def _handle_vehicle_event(self, event_type: str, data: dict[str, Any]) -> None:
        self._trigger_event(event_type, {k: v for k, v in data.items() if v is not None})
        self.async_write_ha_state()
