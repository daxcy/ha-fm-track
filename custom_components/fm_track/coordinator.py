"""Data coordinator: periodic polling, full-record enrichment, trips, events and a live SSE stream."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FmTrackApi, FmTrackAuthError, FmTrackError, FmTrackForbiddenError
from .const import (
    CONF_PLATFORM_EVENTS,
    CONF_SCAN_INTERVAL,
    CONF_TRIPS,
    CONF_USE_STREAM,
    CONF_VEHICLES,
    DEFAULT_PLATFORM_EVENTS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRIPS,
    DEFAULT_USE_STREAM,
    DOMAIN,
    EVENT_FM_TRACK,
    EVENT_IGNITION_OFF,
    EVENT_IGNITION_ON,
    EVENT_PLATFORM,
    EVENT_TRIP_ENDED,
    FEATURE_EVENTS,
    FEATURE_GEOZONES,
    FEATURE_RECORDS,
    FEATURE_STREAM,
    FEATURE_TRIPS,
    BACKFILL_MAX_PAGES,
    BACKFILL_WINDOW,
    GEOZONE_REFRESH,
    RECORD_FALLBACK_WINDOW,
    STREAM_RETRY_MAX,
    STREAM_RETRY_MIN,
    TRIP_HISTORY,
)
from .parser import Trip, VehicleState, backfill, parse_object

_LOGGER = logging.getLogger(__name__)

type FmTrackConfigEntry = ConfigEntry[FmTrackCoordinator]
type EventListener = Callable[[str, dict[str, Any]], None]


class FmTrackCoordinator(DataUpdateCoordinator[dict[str, VehicleState]]):
    """Keeps the state of the selected vehicles up to date."""

    config_entry: FmTrackConfigEntry

    def __init__(self, hass: HomeAssistant, entry: FmTrackConfigEntry, api: FmTrackApi) -> None:
        minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )
        self.api = api
        self._selected: set[str] = set(entry.data.get(CONF_VEHICLES, []))
        self._stream_task: asyncio.Task | None = None

        # None = not tried yet, True = works, False = not in the customer's plan.
        self.features: dict[str, bool | None] = {
            FEATURE_RECORDS: None,
            FEATURE_TRIPS: None,
            FEATURE_EVENTS: None,
            FEATURE_GEOZONES: None,
            FEATURE_STREAM: None,
        }
        self.geozones: dict[str, str] = {}
        self._geozones_at: datetime | None = None
        self.trips: dict[str, list[Trip]] = {}
        self._trips_for: dict[str, datetime | None] = {}
        self._events_since: dict[str, datetime] = {}
        self._backfilled: set[str] = set()
        self.raw_last_coordinate: dict[str, dict[str, Any]] = {}
        self.raw_record: dict[str, dict[str, Any]] = {}

        self.stream_connected = False
        self.stream_last_message: datetime | None = None
        self.stream_messages = 0
        self.raw_stream: dict[str, dict[str, Any]] = {}

        self._event_listeners: dict[str, list[EventListener]] = {}

    # --- options ---------------------------------------------------------

    def _opt(self, key: str, default: Any) -> Any:
        return self.config_entry.options.get(key, default)

    def _wanted(self, object_id: str) -> bool:
        return not self._selected or object_id in self._selected

    def _feature_failed(self, feature: str, err: FmTrackError) -> None:
        if isinstance(err, FmTrackForbiddenError):
            if self.features.get(feature) is not False:
                _LOGGER.info(
                    "FM-Track %s API not available for this key (%s); feature disabled", feature, err
                )
            self.features[feature] = False
        else:
            _LOGGER.debug("FM-Track %s request failed: %s", feature, err)

    # --- polling ---------------------------------------------------------

    async def _async_update_data(self) -> dict[str, VehicleState]:
        try:
            raw_items = await self.api.async_get_vehicles_raw()
        except (FmTrackAuthError, FmTrackForbiddenError) as err:
            raise ConfigEntryAuthFailed("API key rejected") from err
        except FmTrackError as err:
            raise UpdateFailed(f"FM-Track API error: {err}") from err

        current = dict(self.data or {})
        for raw in raw_items:
            state = parse_object(raw)
            if state is None or not self._wanted(state.object_id):
                continue
            self.raw_last_coordinate[state.object_id] = raw
            if state.object_id in current:
                self._merge(current[state.object_id], state)
            else:
                current[state.object_id] = state

        await self._async_refresh_geozones()
        for state in current.values():
            await self._async_enrich(state)
            await self._async_backfill(state)
            await self._async_refresh_trips(state)
            await self._async_check_platform_events(state)
        return current

    async def _async_enrich(self, state: VehicleState) -> None:
        """Fetch the full record (all inputs) for the latest timestamp."""
        if (
            self.features[FEATURE_RECORDS] is False
            or state.datetime is None
            or state.inputs_datetime == state.datetime
        ):
            return
        raw: dict[str, Any] | None = None
        try:
            if state.datetime_raw:
                raw = await self.api.async_get_record(state.object_id, state.datetime_raw)
        except FmTrackForbiddenError as err:
            if err.status == 403:
                self._feature_failed(FEATURE_RECORDS, err)
                return
        except FmTrackError as err:
            self._feature_failed(FEATURE_RECORDS, err)
            return
        if raw is None:
            try:
                raw = await self.api.async_get_latest_record(
                    state.object_id, state.datetime - RECORD_FALLBACK_WINDOW
                )
            except FmTrackError as err:
                self._feature_failed(FEATURE_RECORDS, err)
                return
        if raw is None:
            # Nothing to enrich with; don't retry until a new position arrives.
            state.inputs_datetime = state.datetime
            return
        self.features[FEATURE_RECORDS] = True
        self.raw_record[state.object_id] = raw
        if (record := parse_object(raw)) is not None:
            record.object_id = state.object_id
            if not self._merge(state, record) and record.has_inputs:
                # Slightly older record (e.g. heartbeat vs. GPS fix time):
                # keep the newer position but take over its inputs.
                state.values.update(record.values)
                state.active |= record.active
                state.has_inputs = True
                if state.ignition is None:
                    state.ignition = record.ignition
                if state.geozone_ids is None:
                    state.geozone_ids = record.geozone_ids
                for tire, values in record.tires.items():
                    state.tires.setdefault(tire, {}).update(values)
        state.inputs_datetime = state.datetime

    async def _async_backfill(self, state: VehicleState) -> None:
        """Once per vehicle: last known values of inputs that are sent only now and then."""
        if state.object_id in self._backfilled or self.features[FEATURE_RECORDS] is False:
            return
        self._backfilled.add(state.object_id)
        try:
            raw = await self.api.async_get_records(
                state.object_id, dt_util.utcnow() - BACKFILL_WINDOW, max_pages=BACKFILL_MAX_PAGES
            )
        except FmTrackError as err:
            _LOGGER.debug("Backfill for %s failed: %s", state.object_id, err)
            return
        older = [r for item in raw if (r := parse_object(item)) is not None and r.has_inputs]
        older.sort(key=lambda r: r.datetime or datetime.min.replace(tzinfo=timezone.utc))
        if added := backfill(state, older):
            _LOGGER.debug("Backfilled %s inputs for %s", added, state.object_id)

    async def _async_refresh_geozones(self) -> None:
        if self.features[FEATURE_GEOZONES] is False:
            return
        if not any(s.geozone_ids for s in (self.data or {}).values()) and self._geozones_at:
            return
        now = dt_util.utcnow()
        if self._geozones_at and now - self._geozones_at < GEOZONE_REFRESH:
            return
        try:
            self.geozones = await self.api.async_get_geozones()
            self.features[FEATURE_GEOZONES] = True
        except FmTrackError as err:
            self._feature_failed(FEATURE_GEOZONES, err)
        self._geozones_at = now

    async def _async_refresh_trips(self, state: VehicleState) -> None:
        if not self._opt(CONF_TRIPS, DEFAULT_TRIPS) or self.features[FEATURE_TRIPS] is False:
            return
        oid = state.object_id
        if oid in self._trips_for and self._trips_for[oid] == state.datetime:
            return
        try:
            trips = await self.api.async_get_trips(oid, dt_util.utcnow() - TRIP_HISTORY)
        except FmTrackError as err:
            self._feature_failed(FEATURE_TRIPS, err)
            return
        self.features[FEATURE_TRIPS] = True
        trips.sort(key=lambda t: t.end or t.start or datetime.min.replace(tzinfo=timezone.utc))
        previous = self.last_trip(oid)
        known = oid in self.trips
        self.trips[oid] = trips
        self._trips_for[oid] = state.datetime
        latest = trips[-1] if trips else None
        if known and latest and (previous is None or latest.key != previous.key):
            self._fire(
                state,
                EVENT_TRIP_ENDED,
                {
                    "distance": latest.distance,
                    "duration": latest.duration,
                    "start": latest.start.isoformat() if latest.start else None,
                    "end": latest.end.isoformat() if latest.end else None,
                    "start_address": latest.start_address,
                    "end_address": latest.end_address,
                },
            )

    async def _async_check_platform_events(self, state: VehicleState) -> None:
        if (
            not self._opt(CONF_PLATFORM_EVENTS, DEFAULT_PLATFORM_EVENTS)
            or self.features[FEATURE_EVENTS] is False
        ):
            return
        oid = state.object_id
        now = dt_util.utcnow()
        since = self._events_since.get(oid)
        if since is None:
            self._events_since[oid] = now  # start listening; don't replay history
            return
        try:
            events = await self.api.async_get_detected_events(oid, since, now)
        except FmTrackError as err:
            self._feature_failed(FEATURE_EVENTS, err)
            return
        self.features[FEATURE_EVENTS] = True
        self._events_since[oid] = now
        for event in events:
            start = event.get("start") if isinstance(event.get("start"), dict) else {}
            self._fire(
                state,
                EVENT_PLATFORM,
                {
                    "event_name": event.get("name"),
                    "description": event.get("description"),
                    "start": start.get("datetime"),
                    "duration": event.get("duration"),
                },
            )

    # --- trip helpers (used by sensors) ---------------------------------

    def last_trip(self, object_id: str) -> Trip | None:
        trips = self.trips.get(object_id)
        return trips[-1] if trips else None

    def trips_today(self, object_id: str) -> list[Trip] | None:
        if object_id not in self.trips:
            return None
        midnight = dt_util.start_of_local_day()
        return [t for t in self.trips[object_id] if (t.start or t.end) and (t.start or t.end) >= midnight]

    # --- merging and events ----------------------------------------------

    def _merge(self, existing: VehicleState, update: VehicleState) -> bool:
        old_ignition = existing.ignition
        if not existing.apply(update):
            return False
        new_ignition = existing.ignition
        if old_ignition in ("ON", "OFF") and new_ignition in ("ON", "OFF") and old_ignition != new_ignition:
            self._fire(existing, EVENT_IGNITION_ON if new_ignition == "ON" else EVENT_IGNITION_OFF, {})
        return True

    @callback
    def async_add_event_listener(self, object_id: str, listener: EventListener) -> CALLBACK_TYPE:
        self._event_listeners.setdefault(object_id, []).append(listener)

        @callback
        def _remove() -> None:
            self._event_listeners[object_id].remove(listener)

        return _remove

    def _fire(self, state: VehicleState, event_type: str, extra: dict[str, Any]) -> None:
        device = dr.async_get(self.hass).async_get_device(identifiers={(DOMAIN, state.object_id)})
        data = {
            "type": event_type,
            "object_id": state.object_id,
            "name": state.name,
            "device_id": device.id if device else None,
            **extra,
        }
        self.hass.bus.async_fire(EVENT_FM_TRACK, data)
        for listener in list(self._event_listeners.get(state.object_id, [])):
            listener(event_type, extra)

    # --- streaming -------------------------------------------------------

    def async_start_stream(self) -> None:
        if not self._opt(CONF_USE_STREAM, DEFAULT_USE_STREAM):
            return
        self._stream_task = self.config_entry.async_create_background_task(
            self.hass, self._async_stream_loop(), f"{DOMAIN}_stream"
        )

    @callback
    def _set_stream_connected(self, connected: bool) -> None:
        if self.stream_connected != connected:
            self.stream_connected = connected
            self.async_update_listeners()

    async def _async_stream_loop(self) -> None:
        delay = STREAM_RETRY_MIN
        try:
            while True:
                try:
                    async for raw in self.api.async_stream(
                        on_connect=lambda: self._set_stream_connected(True)
                    ):
                        delay = STREAM_RETRY_MIN
                        self.features[FEATURE_STREAM] = True
                        self.stream_messages += 1
                        self.stream_last_message = dt_util.utcnow()
                        self._handle_stream_record(raw)
                    _LOGGER.debug("Stream closed by server, reconnecting")
                except FmTrackAuthError:
                    _LOGGER.warning("Stream rejected the API key; relying on polling only")
                    self._set_stream_connected(False)
                    return
                except FmTrackForbiddenError as err:
                    self._feature_failed(FEATURE_STREAM, err)
                    self._set_stream_connected(False)
                    return
                except FmTrackError as err:
                    _LOGGER.debug("Stream error (%s), retrying in %ss", err, delay)
                self._set_stream_connected(False)
                await asyncio.sleep(delay)
                delay = min(delay * 2, STREAM_RETRY_MAX)
        finally:
            self.stream_connected = False

    @callback
    def _handle_stream_record(self, raw: dict[str, Any]) -> None:
        update = parse_object(raw)
        if update is None or not self._wanted(update.object_id):
            return
        self.raw_stream[update.object_id] = raw
        data = dict(self.data or {})
        existing = data.get(update.object_id)
        if existing is None:
            return  # unknown object; the next poll will pick it up
        if update.has_inputs:
            self.raw_record[update.object_id] = raw
        if self._merge(existing, update):
            self.async_set_updated_data(data)
