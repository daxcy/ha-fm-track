"""Base entity for FM-Track."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FmTrackCoordinator
from .parser import VehicleState


class FmTrackEntity(CoordinatorEntity[FmTrackCoordinator]):
    """Entity bound to one vehicle."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FmTrackCoordinator, object_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._object_id = object_id
        self._attr_unique_id = f"{object_id}_{key}"
        state = self.vehicle
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, object_id)},
            name=(state.name if state else None) or object_id,
            manufacturer=(state.make if state else None) or None,
            model=(state.model if state else None) or None,
            serial_number=state.vin if state else None,
        )

    @property
    def vehicle(self) -> VehicleState | None:
        return (self.coordinator.data or {}).get(self._object_id)

    @property
    def available(self) -> bool:
        return super().available and self.vehicle is not None
