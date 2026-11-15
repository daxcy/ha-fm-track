"""Sensors for FM-Track vehicles.

A sensor is only created once its value has been reported for a vehicle, so a
car without CAN data does not get a list of permanently unknown entities, and
an electric car does not get fuel sensors. Inputs that are reported but not
covered by a description below become a generic sensor that is disabled by
default, so nothing the platform sends is lost.
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
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfLength,
    UnitOfMass,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .binary_sensor import BINARY_SENSOR_KEYS
from .coordinator import FmTrackConfigEntry, FmTrackCoordinator
from .entity import FmTrackEntity
from .parser import VehicleState, estimate_liion_percent, to_float

type ValueFn = Callable[[FmTrackCoordinator, VehicleState], Any]


@dataclass(frozen=True, kw_only=True)
class FmTrackSensorDescription(SensorEntityDescription):
    value_fn: ValueFn
    # Input keys this sensor consumes (excluded from the generic fallback).
    source_keys: tuple[str, ...] = ()
    placeholders: dict[str, str] | None = None
    fuel_only: bool = False  # hidden for electric vehicles


def _first(*keys: str, scale: float = 1.0, numeric: bool = True) -> ValueFn:
    """First of `keys` that was really reported (0 counts as a value)."""

    def _get(_: FmTrackCoordinator, s: VehicleState) -> Any:
        for key in keys:
            value = s.get(key)
            if value is None:
                continue
            if not numeric:
                return str(value)[:255]
            num = to_float(value)
            return num * scale if num is not None else None
        return None

    return _get


def _input(
    key: str,
    *keys: str,
    scale: float = 1.0,
    numeric: bool = True,
    **kwargs: Any,
) -> FmTrackSensorDescription:
    """Description for a sensor fed by one or more input keys."""
    sources = keys or (key,)
    return FmTrackSensorDescription(
        key=key,
        translation_key=kwargs.pop("translation_key", key),
        value_fn=_first(*sources, scale=scale, numeric=numeric),
        source_keys=sources,
        **kwargs,
    )


def _tracker_battery(_: FmTrackCoordinator, s: VehicleState) -> int | None:
    return estimate_liion_percent(s.get("battery_voltage"))


def _geozone(c: FmTrackCoordinator, s: VehicleState) -> str | None:
    if s.geozone_ids is None or not c.geozones:
        return None  # no geozones defined in the account
    if not s.geozone_ids:
        return "none"
    names = [c.geozones.get(g, g) for g in s.geozone_ids]
    return ", ".join(sorted(names))[:255]


def _hdop(_: FmTrackCoordinator, s: VehicleState) -> float | None:
    return to_float(s.get("hdop"))


def _fuel_liters(_: FmTrackCoordinator, s: VehicleState) -> float | None:
    for key, scale in (("fuel_level_can_l", 1.0), ("fuel_level", 1.0), ("can_fuel_level_milliliters", 0.001)):
        value = to_float(s.get(key))
        if value is not None:
            return round(value * scale, 2)
    return None


def _trip(attr: str) -> ValueFn:
    def _get(c: FmTrackCoordinator, s: VehicleState) -> Any:
        trip = c.last_trip(s.object_id)
        return getattr(trip, attr) if trip else None

    return _get


def _trip_minutes(c: FmTrackCoordinator, s: VehicleState) -> float | None:
    trip = c.last_trip(s.object_id)
    if not trip or trip.duration is None:
        return None
    return round(trip.duration / 60, 1)


def _today_distance(c: FmTrackCoordinator, s: VehicleState) -> float | None:
    trips = c.trips_today(s.object_id)
    if trips is None:
        return None
    return round(sum(t.distance or 0 for t in trips), 1)


def _today_count(c: FmTrackCoordinator, s: VehicleState) -> int | None:
    trips = c.trips_today(s.object_id)
    return None if trips is None else len(trips)


_V = UnitOfElectricPotential.VOLT
_C = UnitOfTemperature.CELSIUS
_KM = UnitOfLength.KILOMETERS
_M = SensorStateClass.MEASUREMENT
_TOTAL_INC = SensorStateClass.TOTAL_INCREASING
_DIAG = EntityCategory.DIAGNOSTIC

SENSORS: list[FmTrackSensorDescription] = [
    # --- position -------------------------------------------------------
    FmTrackSensorDescription(
        key="speed",
        translation_key="speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=_M,
        value_fn=lambda c, s: s.speed,
        source_keys=("gps_speed",),
    ),
    FmTrackSensorDescription(
        key="heading",
        translation_key="heading",
        native_unit_of_measurement=DEGREE,
        entity_registry_enabled_default=False,
        value_fn=lambda c, s: s.direction,
    ),
    FmTrackSensorDescription(
        key="altitude",
        translation_key="altitude",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        entity_registry_enabled_default=False,
        value_fn=lambda c, s: s.altitude,
        source_keys=("gps_altitude",),
    ),
    FmTrackSensorDescription(
        key="satellites",
        translation_key="satellites",
        state_class=_M,
        entity_category=_DIAG,
        value_fn=lambda c, s: s.satellites,
    ),
    FmTrackSensorDescription(
        key="hdop",
        translation_key="hdop",
        state_class=_M,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
        value_fn=_hdop,
        source_keys=("hdop",),
    ),
    FmTrackSensorDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=_DIAG,
        value_fn=lambda c, s: s.datetime,
    ),
    FmTrackSensorDescription(
        key="geozone",
        translation_key="geozone",
        value_fn=_geozone,
    ),
    FmTrackSensorDescription(
        key="trip_type",
        translation_key="trip_type",
        device_class=SensorDeviceClass.ENUM,
        options=["unknown", "none", "private", "business", "work"],
        entity_registry_enabled_default=False,
        value_fn=lambda c, s: s.trip_type.lower() if s.trip_type else None,
    ),
    # --- odometer -------------------------------------------------------
    _input(
        "odometer",
        "mileage",
        "canbus_distance",
        "tco_distance",
        "trailers_high_resolution_vehicle_distance",
        "virtual_odometer",
        "virtual_gps_odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=_KM,
        state_class=_TOTAL_INC,
        suggested_display_precision=0,
    ),
    # --- electric vehicle ----------------------------------------------
    _input(
        "ev_battery",
        "canbus_battery_power",
        "state_of_charge",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=_M,
    ),
    _input(
        "ev_range",
        "canbus_distance_until_recharge",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=_KM,
        state_class=_M,
    ),
    _input(
        "electric_motor_temperature",
        "canbus_electric_motor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=_C,
        state_class=_M,
    ),
    _input(
        "dxp_battery",
        "dxp_battery_state_of_charge",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=_M,
    ),
    _input(
        "dxp_battery_voltage",
        "dxp_battery_battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=_V,
        state_class=_M,
        entity_registry_enabled_default=False,
    ),
    _input(
        "dxp_battery_temperature",
        "dxp_battery_battery_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=_C,
        state_class=_M,
        entity_registry_enabled_default=False,
    ),
    # --- power supply / tracker battery ---------------------------------
    _input(
        "supply_voltage",
        "power_supply_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=_V,
        state_class=_M,
        suggested_display_precision=2,
    ),
    FmTrackSensorDescription(
        key="tracker_battery",
        translation_key="tracker_battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=_M,
        value_fn=_tracker_battery,
    ),
    _input(
        "tracker_battery_voltage",
        "battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=_V,
        state_class=_M,
        entity_category=_DIAG,
        suggested_display_precision=2,
    ),
    _input(
        "tracker_battery_current",
        "battery_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        state_class=_M,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    # --- fuel (not for electric vehicles) -------------------------------
    FmTrackSensorDescription(
        key="fuel_level",
        translation_key="fuel_level",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=_M,
        value_fn=_fuel_liters,
        source_keys=("fuel_level_can_l", "fuel_level", "can_fuel_level_milliliters"),
        fuel_only=True,
    ),
    _input(
        "fuel_level_percent",
        "fuel_level_can",
        "obd_kline_fuel_level_input",
        native_unit_of_measurement=PERCENTAGE,
        state_class=_M,
        fuel_only=True,
    ),
    _input(
        "fuel_used",
        "canbus_hrfc",
        "fuel_used",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=_TOTAL_INC,
        fuel_only=True,
    ),
    _input(
        "fuel_rate",
        "canbus_fuel_rate",
        "obd_kline_engine_fuel_rate",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_HOUR,
        state_class=_M,
        entity_registry_enabled_default=False,
        fuel_only=True,
    ),
    _input(
        "fuel_economy",
        "canbus_fuel_economy",
        native_unit_of_measurement="km/L",
        state_class=_M,
        entity_registry_enabled_default=False,
        fuel_only=True,
    ),
    # --- engine --------------------------------------------------------
    _input(
        "rpm",
        "engine_rpm",
        "obd_kline_rpm",
        "tco_rpm",
        "rpm",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=_M,
    ),
    _input(
        "coolant_temperature",
        "canbus_engine_coolant_temperature",
        "obd_kline_engine_coolant_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=_C,
        state_class=_M,
    ),
    _input(
        "engine_hours",
        "engine_hours",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=_TOTAL_INC,
    ),
    _input(
        "engine_load",
        "canbus_engine_plcs",
        "obd_kline_actual_engine_percent_torque",
        native_unit_of_measurement=PERCENTAGE,
        state_class=_M,
        entity_registry_enabled_default=False,
    ),
    _input(
        "accelerator_pedal",
        "pedal_pos",
        "obd_kline_relative_accelerator_pedal_position",
        native_unit_of_measurement=PERCENTAGE,
        state_class=_M,
        entity_registry_enabled_default=False,
    ),
    _input(
        "obd_dtc_count",
        "obd_kline_dtc_counted",
        state_class=_M,
        entity_category=_DIAG,
    ),
    _input(
        "distance_with_mil",
        "obd_kline_distance_traveled_while_mil_is_activated",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=_KM,
        state_class=_M,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    _input(
        "ambient_temperature",
        "canbus_ambient_air_temperature",
        "obd_kline_ambient_air_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=_C,
        state_class=_M,
    ),
    # --- service --------------------------------------------------------
    _input(
        "service_distance",
        "service_dist",
        "trailers_service_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=_KM,
        state_class=_M,
    ),
    _input(
        "service_hours",
        "canbus_hours_to_service",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=_M,
    ),
    # --- load -----------------------------------------------------------
    _input(
        "weight",
        "weight",
        "kimax_total_truck_weight",
        "trailers_axle_load_sum",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=_M,
    ),
    # --- connectivity / device health -----------------------------------
    _input(
        "gsm_signal",
        "gsm_umts_signal_strength",
        "gsm_signal_strength",
        state_class=_M,
        entity_category=_DIAG,
    ),
    _input(
        "modem_temperature",
        "modem_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=_C,
        state_class=_M,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    _input(
        "device_temperature",
        "pcb_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=_C,
        state_class=_M,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    # --- driver identification (privacy: off by default) ----------------
    _input(
        "driver_id",
        "ibutton",
        "first_driver_id",
        "rfid_a",
        "rfid_b",
        "magnetic_card_id",
        "wireless_driver_id",
        numeric=False,
        entity_registry_enabled_default=False,
    ),
    # --- trips ----------------------------------------------------------
    FmTrackSensorDescription(
        key="last_trip_distance",
        translation_key="last_trip_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=_KM,
        suggested_display_precision=1,
        value_fn=_trip("distance"),
    ),
    FmTrackSensorDescription(
        key="last_trip_duration",
        translation_key="last_trip_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=_trip_minutes,
    ),
    FmTrackSensorDescription(
        key="last_trip_start",
        translation_key="last_trip_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
        value_fn=_trip("start"),
    ),
    FmTrackSensorDescription(
        key="last_trip_end",
        translation_key="last_trip_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_trip("end"),
    ),
    FmTrackSensorDescription(
        key="last_trip_start_address",
        translation_key="last_trip_start_address",
        entity_registry_enabled_default=False,
        value_fn=_trip("start_address"),
    ),
    FmTrackSensorDescription(
        key="last_trip_end_address",
        translation_key="last_trip_end_address",
        value_fn=_trip("end_address"),
    ),
    FmTrackSensorDescription(
        key="last_trip_fuel",
        translation_key="last_trip_fuel",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        entity_registry_enabled_default=False,
        value_fn=lambda c, s: (t.fuel or None) if (t := c.last_trip(s.object_id)) else None,
        fuel_only=True,
    ),
    FmTrackSensorDescription(
        key="distance_today",
        translation_key="distance_today",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=_KM,
        state_class=_TOTAL_INC,
        suggested_display_precision=1,
        value_fn=_today_distance,
    ),
    FmTrackSensorDescription(
        key="trips_today",
        translation_key="trips_today",
        state_class=_M,
        value_fn=_today_count,
    ),
]

# Numbered sensors (temperature probes, humidity, axles, analog inputs, ...).
for i in range(4):
    SENSORS.append(_input(f"temperature_{i}", f"temperature_sensor_{i}", translation_key="temperature_n",
                          placeholders={"index": str(i)}, device_class=SensorDeviceClass.TEMPERATURE,
                          native_unit_of_measurement=_C, state_class=_M))
for i in range(1, 6):
    SENSORS.append(_input(f"bt_temperature_{i}", f"bt_temperature_sensor_{i}", translation_key="bt_temperature_n",
                          placeholders={"index": str(i)}, device_class=SensorDeviceClass.TEMPERATURE,
                          native_unit_of_measurement=_C, state_class=_M))
for i in range(1, 7):
    SENSORS.append(_input(f"ot_temperature_{i}", f"ot_temperature_sensor_{i}", translation_key="ot_temperature_n",
                          placeholders={"index": str(i)}, device_class=SensorDeviceClass.TEMPERATURE,
                          native_unit_of_measurement=_C, state_class=_M))
    SENSORS.append(_input(f"tk_temperature_{i}", f"tk_temperature_sensor{i}", translation_key="tk_temperature_n",
                          placeholders={"index": str(i)}, device_class=SensorDeviceClass.TEMPERATURE,
                          native_unit_of_measurement=_C, state_class=_M))
for i in range(5):
    SENSORS.append(_input(f"bt_humidity_{i}", f"bt_humidity_sensor_{i}", translation_key="humidity_n",
                          placeholders={"index": str(i)}, device_class=SensorDeviceClass.HUMIDITY,
                          native_unit_of_measurement=PERCENTAGE, state_class=_M))
for i in range(1, 6):
    SENSORS.append(_input(f"axle_weight_{i}", f"canbus_axle_weight_{i}", translation_key="axle_weight_n",
                          placeholders={"index": str(i)}, device_class=SensorDeviceClass.WEIGHT,
                          native_unit_of_measurement=UnitOfMass.KILOGRAMS, state_class=_M,
                          entity_registry_enabled_default=False))
for i in range(1, 3):
    SENSORS.append(_input(f"analog_input_{i}", f"analog_input_{i}", translation_key="analog_input_n",
                          placeholders={"index": str(i)}, device_class=SensorDeviceClass.VOLTAGE,
                          native_unit_of_measurement=_V, state_class=_M, entity_registry_enabled_default=False))
    SENSORS.append(_input(f"frequency_input_{i}", f"frequency_input_{i}", translation_key="frequency_input_n",
                          placeholders={"index": str(i)}, device_class=SensorDeviceClass.FREQUENCY,
                          native_unit_of_measurement=UnitOfFrequency.HERTZ, state_class=_M,
                          entity_registry_enabled_default=False))
for i in range(1, 9):
    # Platform-configured calculated inputs; only created when non-zero.
    SENSORS.append(_input(f"custom_input_{i}", f"custom_input_{i}", translation_key="custom_input_n",
                          placeholders={"index": str(i)}, state_class=_M))
SENSORS.append(_input("temperature", "temperature", device_class=SensorDeviceClass.TEMPERATURE,
                      native_unit_of_measurement=_C, state_class=_M))

SENSOR_KEYS: set[str] = {k for d in SENSORS for k in d.source_keys}

# Never worth a generic entity.
_GENERIC_IGNORE_PREFIXES = ("can_interface_configuration_", "can_lcv_configuration_", "mobileye_vision", "mobileye_sign_")
_GENERIC_IGNORE = {"country_code_geonames", "input_trigger", "priority"}

# Tyre values that become sensors (tyre key → (suffix, device class, unit)).
_TIRE_SENSORS = {
    "tire_pressure": ("pressure", SensorDeviceClass.PRESSURE, UnitOfPressure.KPA),
    "tire_temperature": ("temperature", SensorDeviceClass.TEMPERATURE, _C),
}


def _humanize(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FmTrackConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    added: set[tuple[str, str]] = set()

    @callback
    def _add_new() -> None:
        new: list[SensorEntity] = []
        for object_id, state in (coordinator.data or {}).items():
            for desc in SENSORS:
                if (object_id, desc.key) in added:
                    continue
                if desc.fuel_only and state.is_electric:
                    continue
                if desc.value_fn(coordinator, state) is None:
                    continue
                added.add((object_id, desc.key))
                new.append(FmTrackSensor(coordinator, object_id, desc))
            for tire, values in state.tires.items():
                for value_key, (suffix, device_class, unit) in _TIRE_SENSORS.items():
                    uid = f"{tire}_{suffix}"
                    if (object_id, uid) in added or value_key not in values:
                        continue
                    added.add((object_id, uid))
                    new.append(FmTrackTireSensor(coordinator, object_id, tire, value_key, suffix, device_class, unit))
            for key in sorted(state.active):
                if (
                    key in SENSOR_KEYS
                    or key in BINARY_SENSOR_KEYS
                    or key in _GENERIC_IGNORE
                    or key.startswith(_GENERIC_IGNORE_PREFIXES)
                    or isinstance(state.values.get(key), bool)
                    or (object_id, f"input_{key}") in added
                ):
                    continue
                added.add((object_id, f"input_{key}"))
                new.append(FmTrackGenericSensor(coordinator, object_id, key))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class FmTrackSensor(FmTrackEntity, SensorEntity):
    entity_description: FmTrackSensorDescription

    def __init__(self, coordinator: FmTrackCoordinator, object_id: str, desc: FmTrackSensorDescription) -> None:
        super().__init__(coordinator, object_id, desc.key, desc.placeholders)
        self.entity_description = desc
        state = self.vehicle
        if desc.key == "tracker_battery" and state and (to_float(state.get("power_supply_voltage")) or 0) > 5:
            # Backup battery of a tracker that runs on vehicle power: diagnostic only.
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> Any:
        v = self.vehicle
        return self.entity_description.value_fn(self.coordinator, v) if v else None


class FmTrackTireSensor(FmTrackEntity, SensorEntity):
    """Pressure or temperature of one tyre (TPMS)."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, object_id, tire, value_key, suffix, device_class, unit) -> None:
        digits = "".join(ch for ch in tire if ch.isdigit())
        index = str(int(digits)) if digits else tire
        super().__init__(coordinator, object_id, f"{tire}_{suffix}", {"index": index})
        self._tire = tire
        self._value_key = value_key
        self._attr_translation_key = f"tire_{suffix}"
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> float | None:
        v = self.vehicle
        return v.tires.get(self._tire, {}).get(self._value_key) if v else None


class FmTrackGenericSensor(FmTrackEntity, SensorEntity):
    """Any other reported input; disabled by default."""

    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: FmTrackCoordinator, object_id: str, key: str) -> None:
        super().__init__(coordinator, object_id, f"input_{key}")
        self._key = key
        self._attr_name = _humanize(key)
        if isinstance(self._current, (int, float)):
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def _current(self) -> Any:
        v = self.vehicle
        return v.get(self._key) if v else None

    @property
    def native_value(self) -> Any:
        value = self._current
        if isinstance(value, str):
            return value[:255]
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"input": self._key}
