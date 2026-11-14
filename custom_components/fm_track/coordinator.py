"""Data coordinator: periodic polling plus a live SSE stream."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FmTrackApi, FmTrackAuthError, FmTrackError
from .const import (
    CONF_USE_STREAM,
    CONF_VEHICLES,
    DEFAULT_USE_STREAM,
    DOMAIN,
    EVENT_FM_TRACK,
    POLL_INTERVAL,
    STREAM_RETRY_MAX,
    STREAM_RETRY_MIN,
)
from .parser import VehicleState

_LOGGER = logging.getLogger(__name__)

type FmTrackConfigEntry = ConfigEntry[FmTrackCoordinator]


class FmTrackCoordinator(DataUpdateCoordinator[dict[str, VehicleState]]):
    """Keeps the state of the selected vehicles up to date."""

    config_entry: FmTrackConfigEntry

    def __init__(self, hass: HomeAssistant, entry: FmTrackConfigEntry, api: FmTrackApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=POLL_INTERVAL,
        )
        self.api = api
        self._selected: set[str] = set(entry.data.get(CONF_VEHICLES, []))
        self._stream_task: asyncio.Task | None = None

    async def _async_update_data(self) -> dict[str, VehicleState]:
        try:
            fresh = await self.api.async_get_vehicles()
        except FmTrackAuthError as err:
            raise ConfigEntryAuthFailed("API key rejected") from err
        except FmTrackError as err:
            raise UpdateFailed(f"FM-Track API error: {err}") from err

        current = dict(self.data or {})
        for object_id, state in fresh.items():
            if self._selected and object_id not in self._selected:
                continue
            if object_id in current:
                self._merge(current[object_id], state)
            else:
                current[object_id] = state
        return current

    def _merge(self, existing: VehicleState, update: VehicleState) -> bool:
        old_ignition = existing.ignition
        if not existing.apply(update):
            return False
        if old_ignition in ("ON", "OFF") and existing.ignition in ("ON", "OFF") and old_ignition != existing.ignition:
            self.hass.bus.async_fire(
                EVENT_FM_TRACK,
                {
                    "type": "ignition_on" if existing.ignition == "ON" else "ignition_off",
                    "object_id": existing.object_id,
                    "name": existing.name,
                },
            )
        return True

    # --- streaming -------------------------------------------------------

    def async_start_stream(self) -> None:
        if not self.config_entry.options.get(CONF_USE_STREAM, DEFAULT_USE_STREAM):
            return
        self._stream_task = self.config_entry.async_create_background_task(
            self.hass, self._async_stream_loop(), f"{DOMAIN}_stream"
        )

    async def _async_stream_loop(self) -> None:
        delay = STREAM_RETRY_MIN
        while True:
            try:
                async for update in self.api.async_stream():
                    delay = STREAM_RETRY_MIN
                    if self._selected and update.object_id not in self._selected:
                        continue
                    data = dict(self.data or {})
                    existing = data.get(update.object_id)
                    if existing is None:
                        continue  # unknown object; the next poll will pick it up
                    if self._merge(existing, update):
                        self.async_set_updated_data(data)
                _LOGGER.debug("Stream closed by server, reconnecting")
            except FmTrackAuthError:
                _LOGGER.warning("Stream rejected the API key; relying on polling only")
                return
            except FmTrackError as err:
                _LOGGER.debug("Stream error (%s), retrying in %ss", err, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, STREAM_RETRY_MAX)
