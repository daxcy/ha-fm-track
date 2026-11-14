"""Binary sensors for FM-Track vehicles (created once a value is seen)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FmTrackConfigEntry, FmTrackCoordinator
from .entity import FmTrackEntity
from .parser import VehicleState


@dataclass(frozen=True, kw_only=True)
class FmTrackBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[VehicleState], bool | None]


def _enum(key: str, on: str, off: str) -> Callable[[VehicleState], bool | None]:
    def _get(s: VehicleState) -> bool | None:
        value = s.values.get(key)
        if value == on:
            return True
        if value == off:
            return False
        return None

    return _get


def _ignition(s: VehicleState) -> bool | None:
    if s.ignition == "ON":
        return True
    if s.ignition == "OFF":
        return False
    return _enum("can_ignition", "ON", "OFF")(s)


BINARY_SENSORS: tuple[FmTrackBinaryDescription, ...] = (
    FmTrackBinaryDescription(
        key="ignition",
        translation_key="ignition",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=_ignition,
    ),
    FmTrackBinaryDescription(
        key="moving",
        translation_key="moving",
        device_class=BinarySensorDeviceClass.MOVING,
        value_fn=lambda s: None if s.speed is None else s.speed > 3,
    ),
    FmTrackBinaryDescription(
        key="lock",
        translation_key="lock",
        device_class=BinarySensorDeviceClass.LOCK,  # on = unlocked
        value_fn=_enum("can_door_lock_state", "UNLOCKED", "LOCKED"),
    ),
    FmTrackBinaryDescription(
        key="driver_door",
        translation_key="driver_door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_enum("lcv_driver_doors", "OPEN", "CLOSE"),
    ),
    FmTrackBinaryDescription(
        key="passenger_door",
        translation_key="passenger_door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_enum("lcv_passenger_doors", "OPEN", "CLOSE"),
    ),
    FmTrackBinaryDescription(
        key="trunk",
        translation_key="trunk",
        device_class=BinarySensorDeviceClass.OPENING,
        value_fn=_enum("lcv_trunk", "OPEN", "CLOSE"),
    ),
    FmTrackBinaryDescription(
        key="hood",
        translation_key="hood",
        device_class=BinarySensorDeviceClass.OPENING,
        value_fn=_enum("lcv_hood", "OPEN", "CLOSE"),
    ),
    FmTrackBinaryDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=_enum("canbus_battery_charging", "CHARGING", "NO_CHARGING"),
    ),
    FmTrackBinaryDescription(
        key="jamming",
        translation_key="jamming",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_enum("gsm_umts_jamming", "JAMMING_DETECTED", "JAMMING_NOT_DETECTED"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FmTrackConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    added: set[tuple[str, str]] = set()

    @callback
    def _add_new() -> None:
        new: list[FmTrackBinarySensor] = []
        for object_id, state in (coordinator.data or {}).items():
            for desc in BINARY_SENSORS:
                if (object_id, desc.key) in added or desc.value_fn(state) is None:
                    continue
                added.add((object_id, desc.key))
                new.append(FmTrackBinarySensor(coordinator, object_id, desc))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class FmTrackBinarySensor(FmTrackEntity, BinarySensorEntity):
    entity_description: FmTrackBinaryDescription

    def __init__(self, coordinator: FmTrackCoordinator, object_id: str, desc: FmTrackBinaryDescription) -> None:
        super().__init__(coordinator, object_id, desc.key)
        self.entity_description = desc

    @property
    def is_on(self) -> bool | None:
        v = self.vehicle
        return self.entity_description.value_fn(v) if v else None
