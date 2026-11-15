"""Binary sensors for FM-Track vehicles (created once a value is reported)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import FmTrackConfigEntry, FmTrackCoordinator
from .entity import FmTrackEntity, account_device_info
from .parser import VehicleState, to_float

type BoolFn = Callable[[VehicleState], bool | None]


@dataclass(frozen=True, kw_only=True)
class FmTrackBinaryDescription(BinarySensorEntityDescription):
    value_fn: BoolFn
    source_keys: tuple[str, ...] = ()
    placeholders: dict[str, str] | None = None


def _to_bool(value: Any, on: tuple[str, ...], off: tuple[str, ...]) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        upper = value.upper()
        if upper in on:
            return True
        if upper in off:
            return False
        if upper in ("TRUE", "1"):
            return True
        if upper in ("FALSE", "0"):
            return False
    return None


def _state(*keys: str, on: tuple[str, ...] = ("ON",), off: tuple[str, ...] = ("OFF",)) -> BoolFn:
    def _get(s: VehicleState) -> bool | None:
        for key in keys:
            result = _to_bool(s.get(key), on, off)
            if result is not None:
                return result
        return None

    return _get


def _desc(key: str, *keys: str, on=("ON",), off=("OFF",), **kwargs: Any) -> FmTrackBinaryDescription:
    sources = keys or (key,)
    return FmTrackBinaryDescription(
        key=key,
        translation_key=kwargs.pop("translation_key", key),
        value_fn=_state(*sources, on=on, off=off),
        source_keys=sources,
        **kwargs,
    )


def _ignition(s: VehicleState) -> bool | None:
    if s.ignition in ("ON", "OFF"):
        return s.ignition == "ON"
    return _state("can_ignition", "custom_ignition", "ignition_plugtrack")(s)


def _moving(s: VehicleState) -> bool | None:
    movement = s.get("movement")
    if isinstance(movement, str) and movement.upper() in ("MOVING", "STILL"):
        return movement.upper() == "MOVING"
    return None if s.speed is None else s.speed > 3


def _external_power(s: VehicleState) -> bool | None:
    volts = to_float(s.get("power_supply_voltage"))
    return None if volts is None else volts > 5


_OPEN = ("OPEN",)
_CLOSED = ("CLOSE", "CLOSED")
_DIAG = EntityCategory.DIAGNOSTIC

BINARY_SENSORS: list[FmTrackBinaryDescription] = [
    FmTrackBinaryDescription(
        key="ignition",
        translation_key="ignition",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=_ignition,
        source_keys=("can_ignition", "custom_ignition", "ignition_plugtrack"),
    ),
    FmTrackBinaryDescription(
        key="moving",
        translation_key="moving",
        device_class=BinarySensorDeviceClass.MOVING,
        value_fn=_moving,
        source_keys=("movement",),
    ),
    FmTrackBinaryDescription(
        key="external_power",
        translation_key="external_power",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
        value_fn=_external_power,
    ),
    # EV
    _desc("charging", "canbus_battery_charging", on=("CHARGING",), off=("NO_CHARGING",),
          device_class=BinarySensorDeviceClass.BATTERY_CHARGING),
    # body
    _desc("lock", "can_door_lock_state", on=("UNLOCKED",), off=("LOCKED",),
          device_class=BinarySensorDeviceClass.LOCK),  # on = unlocked
    _desc("driver_door", "lcv_driver_doors", on=_OPEN, off=_CLOSED, device_class=BinarySensorDeviceClass.DOOR),
    _desc("passenger_door", "lcv_passenger_doors", on=_OPEN, off=_CLOSED, device_class=BinarySensorDeviceClass.DOOR),
    _desc("rear_left_door", "lcv_left_back_doors", on=_OPEN, off=_CLOSED, device_class=BinarySensorDeviceClass.DOOR),
    _desc("rear_right_door", "lcv_right_back_doors", on=_OPEN, off=_CLOSED, device_class=BinarySensorDeviceClass.DOOR),
    _desc("trunk", "lcv_trunk", on=_OPEN, off=_CLOSED, device_class=BinarySensorDeviceClass.OPENING),
    _desc("hood", "lcv_hood", on=_OPEN, off=_CLOSED, device_class=BinarySensorDeviceClass.OPENING),
    _desc("window_front_left", "can_lcv_window_state_front_left", device_class=BinarySensorDeviceClass.WINDOW),
    _desc("window_front_right", "can_lcv_window_state_front_right", device_class=BinarySensorDeviceClass.WINDOW),
    _desc("window_rear_left", "can_lcv_window_state_back_left", device_class=BinarySensorDeviceClass.WINDOW),
    _desc("window_rear_right", "can_lcv_window_state_back_right", device_class=BinarySensorDeviceClass.WINDOW),
    _desc("sunroof", "can_lcv_window_state_sunroof", device_class=BinarySensorDeviceClass.WINDOW),
    _desc("parking_brake", "canbus_parking_brake_switch"),
    _desc("cruise_control", "canbus_cruise_control_state", entity_registry_enabled_default=False),
    _desc("brake_pedal", "canbus_brake_switch", on=("PRESSED",), off=("RELEASED",),
          entity_registry_enabled_default=False),
    _desc("clutch_pedal", "canbus_clutch_switch", on=("PRESSED",), off=("RELEASED",),
          entity_registry_enabled_default=False),
    # alarms
    _desc("panic", "panic", device_class=BinarySensorDeviceClass.SAFETY),
    _desc("rollover", "roll_over_alarm", device_class=BinarySensorDeviceClass.SAFETY),
    _desc("jamming", "gsm_umts_jamming", on=("JAMMING_DETECTED",), off=("JAMMING_NOT_DETECTED",),
          device_class=BinarySensorDeviceClass.PROBLEM, entity_category=_DIAG),
    # connectivity
    _desc("gprs", "gprs_status", on=("CONNECTED",), off=("DISCONNECTED",),
          device_class=BinarySensorDeviceClass.CONNECTIVITY, entity_category=_DIAG,
          entity_registry_enabled_default=False),
    _desc("gnss_antenna", "gnss_antenna", on=("ENABLED",), off=("DISABLED",),
          device_class=BinarySensorDeviceClass.CONNECTIVITY, entity_category=_DIAG,
          entity_registry_enabled_default=False),
]
for i in range(1, 5):
    BINARY_SENSORS.append(_desc(f"digital_input_{i}", f"digital_input_{i}", translation_key="digital_input_n",
                                placeholders={"index": str(i)}, entity_registry_enabled_default=False))
    BINARY_SENSORS.append(_desc(f"ot_digital_input_{i}", f"ot_digital_input_{i}", translation_key="ot_digital_input_n",
                                placeholders={"index": str(i)}, entity_registry_enabled_default=False))
for i in range(1, 3):
    BINARY_SENSORS.append(_desc(f"output_{i}", f"dout{i}_status", on=("ACTIVE",), off=("INACTIVE",),
                                translation_key="output_n", placeholders={"index": str(i)},
                                entity_registry_enabled_default=False))

BINARY_SENSOR_KEYS: set[str] = {k for d in BINARY_SENSORS for k in d.source_keys} | {"movement"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FmTrackConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    added: set[tuple[str, str]] = set()
    async_add_entities([FmTrackStreamSensor(coordinator)])

    @callback
    def _add_new() -> None:
        new: list[BinarySensorEntity] = []
        for object_id, state in (coordinator.data or {}).items():
            for desc in BINARY_SENSORS:
                if (object_id, desc.key) in added or desc.value_fn(state) is None:
                    continue
                added.add((object_id, desc.key))
                new.append(FmTrackBinarySensor(coordinator, object_id, desc))
            for key in sorted(state.active):
                # Other boolean inputs (e.g. Mobileye flags): generic, disabled.
                if key in BINARY_SENSOR_KEYS or not isinstance(state.values.get(key), bool):
                    continue
                if (object_id, f"input_{key}") in added:
                    continue
                added.add((object_id, f"input_{key}"))
                new.append(FmTrackGenericBinarySensor(coordinator, object_id, key))
            for tire, values in state.tires.items():
                uid = f"{tire}_leak"
                if (object_id, uid) in added or "tire_status" not in values:
                    continue
                added.add((object_id, uid))
                new.append(FmTrackTireLeakSensor(coordinator, object_id, tire))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class FmTrackBinarySensor(FmTrackEntity, BinarySensorEntity):
    entity_description: FmTrackBinaryDescription

    def __init__(self, coordinator: FmTrackCoordinator, object_id: str, desc: FmTrackBinaryDescription) -> None:
        super().__init__(coordinator, object_id, desc.key, desc.placeholders)
        self.entity_description = desc

    @property
    def is_on(self) -> bool | None:
        v = self.vehicle
        return self.entity_description.value_fn(v) if v else None


class FmTrackGenericBinarySensor(FmTrackEntity, BinarySensorEntity):
    """Any other boolean input; disabled by default."""

    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: FmTrackCoordinator, object_id: str, key: str) -> None:
        super().__init__(coordinator, object_id, f"input_{key}")
        self._key = key
        self._attr_name = key.replace("_", " ").strip().capitalize()

    @property
    def is_on(self) -> bool | None:
        v = self.vehicle
        value = v.get(self._key) if v else None
        return value if isinstance(value, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"input": self._key}


class FmTrackTireLeakSensor(FmTrackEntity, BinarySensorEntity):
    """Tyre problem from TPMS status (1 = leak detected, 2 = error)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "tire_problem"

    def __init__(self, coordinator: FmTrackCoordinator, object_id: str, tire: str) -> None:
        digits = "".join(ch for ch in tire if ch.isdigit())
        index = str(int(digits)) if digits else tire
        super().__init__(coordinator, object_id, f"{tire}_leak", {"index": index})
        self._tire = tire

    @property
    def is_on(self) -> bool | None:
        v = self.vehicle
        status = v.tires.get(self._tire, {}).get("tire_status") if v else None
        return None if status is None else int(status) in (1, 2)


class FmTrackStreamSensor(CoordinatorEntity[FmTrackCoordinator], BinarySensorEntity):
    """Whether the live stream is connected (on the account device)."""

    _attr_has_entity_name = True
    _attr_translation_key = "live_stream"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: FmTrackCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_live_stream"
        self._attr_device_info = account_device_info(coordinator)

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.stream_connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator
        return {
            "messages": c.stream_messages,
            "last_message": c.stream_last_message.isoformat() if c.stream_last_message else None,
            "features": {k: v for k, v in c.features.items()},
        }
