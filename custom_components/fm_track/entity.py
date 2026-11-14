"""Base entities for FM-Track."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FmTrackCoordinator
from .parser import VehicleState


def account_device_info(coordinator: FmTrackCoordinator) -> DeviceInfo:
    """The account ("hub") device the vehicles hang under."""
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        name="FM-Track",
        manufacturer="FM-Track",
        model="Fleet API",
        entry_type=DeviceEntryType.SERVICE,
    )


class FmTrackEntity(CoordinatorEntity[FmTrackCoordinator]):
    """Entity bound to one vehicle."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FmTrackCoordinator,
        object_id: str,
        key: str,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._object_id = object_id
        self._attr_unique_id = f"{object_id}_{key}"
        if placeholders:
            self._attr_translation_placeholders = placeholders
        state = self.vehicle
        model = " ".join(p for p in ((state.make, state.model) if state else ()) if p) or None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, object_id)},
            name=(state.name if state else None) or object_id,
            manufacturer=(state.make if state else None) or None,
            model=model,
            serial_number=(state.vin if state else None) or None,
            via_device=(DOMAIN, coordinator.config_entry.entry_id),
        )

    @property
    def vehicle(self) -> VehicleState | None:
        return (self.coordinator.data or {}).get(self._object_id)

    @property
    def available(self) -> bool:
        return super().available and self.vehicle is not None
