"""Sensors for FM-Track vehicles.

A sensor is only created once its value has been seen for a vehicle, so cars
without CAN data do not get a list of permanently unknown entities.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfLength,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FmTrackConfigEntry, FmTrackCoordinator
from .entity import FmTrackEntity
from .parser import VehicleState


@dataclass(frozen=True, kw_only=True)
class FmTrackSensorDescription(SensorEntityDescription):
    value_fn: Callable[[VehicleState], Any]


def _v(*keys: str) -> Callable[[VehicleState], Any]:
    """Return the first of `keys` that has a value (0 counts as a value)."""

    def _get(s: VehicleState) -> Any:
        for key in keys:
            if (value := s.values.get(key)) is not None:
                return value
        return None

    return _get


SENSORS: tuple[FmTrackSensorDescription, ...] = (
    FmTrackSensorDescription(
        key="speed",
        translation_key="speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.speed,
    ),
    FmTrackSensorDescription(
        key="heading",
        translation_key="heading",
        native_unit_of_measurement=DEGREE,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.direction,
    ),
    FmTrackSensorDescription(
        key="altitude",
        translation_key="altitude",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.altitude,
    ),
    FmTrackSensorDescription(
        key="satellites",
        translation_key="satellites",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.satellites,
    ),
    FmTrackSensorDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.datetime,
    ),
    FmTrackSensorDescription(
        key="trip_type",
        translation_key="trip_type",
        device_class=SensorDeviceClass.ENUM,
        options=["unknown", "none", "private", "business", "work"],
        value_fn=lambda s: s.trip_type.lower() if s.trip_type else None,
    ),
    FmTrackSensorDescription(
        key="odometer",
        translation_key="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_v("mileage", "canbus_distance", "virtual_gps_odometer"),
    ),
    FmTrackSensorDescription(
        key="fuel_level",
        translation_key="fuel_level",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_v("fuel_level", "fuel_level_can_l"),
    ),
    FmTrackSensorDescription(
        key="fuel_level_percent",
        translation_key="fuel_level_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_v("fuel_level_can"),
    ),
    FmTrackSensorDescription(
        key="ev_battery",
        translation_key="ev_battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_v("canbus_battery_power"),
    ),
    FmTrackSensorDescription(
        key="ev_range",
        translation_key="ev_range",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_v("canbus_distance_until_recharge"),
    ),
    FmTrackSensorDescription(
        key="rpm",
        translation_key="rpm",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_v("engine_rpm", "rpm"),
    ),
    FmTrackSensorDescription(
        key="coolant_temperature",
        translation_key="coolant_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_v("canbus_engine_coolant_temperature"),
    ),
    FmTrackSensorDescription(
        key="ambient_temperature",
        translation_key="ambient_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_v("canbus_ambient_air_temperature"),
    ),
    FmTrackSensorDescription(
        key="engine_hours",
        translation_key="engine_hours",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_v("engine_hours"),
    ),
    FmTrackSensorDescription(
        key="service_distance",
        translation_key="service_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        value_fn=_v("service_dist"),
    ),
    FmTrackSensorDescription(
        key="gsm_signal",
        translation_key="gsm_signal",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_v("gsm_umts_signal_strength", "gsm_signal_strength"),
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
        new: list[FmTrackSensor] = []
        for object_id, state in (coordinator.data or {}).items():
            for desc in SENSORS:
                if (object_id, desc.key) in added or desc.value_fn(state) is None:
                    continue
                added.add((object_id, desc.key))
                new.append(FmTrackSensor(coordinator, object_id, desc))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class FmTrackSensor(FmTrackEntity, SensorEntity):
    entity_description: FmTrackSensorDescription

    def __init__(self, coordinator: FmTrackCoordinator, object_id: str, desc: FmTrackSensorDescription) -> None:
        super().__init__(coordinator, object_id, desc.key)
        self.entity_description = desc

    @property
    def native_value(self) -> Any:
        v = self.vehicle
        return self.entity_description.value_fn(v) if v else None
