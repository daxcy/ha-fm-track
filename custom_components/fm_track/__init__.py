"""The FM-Track integration."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DEFAULT_BASE_URL, FmTrackApi
from .const import CONF_BASE_URL
from .coordinator import FmTrackConfigEntry, FmTrackCoordinator
from .entity import account_device_info

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.EVENT,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: FmTrackConfigEntry) -> bool:
    """Set up FM-Track from a config entry."""
    api = FmTrackApi(
        async_get_clientsession(hass),
        entry.data[CONF_API_KEY],
        entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
    )
    coordinator = FmTrackCoordinator(hass, entry, api)
    registry = dr.async_get(hass)
    account = registry.async_get_or_create(config_entry_id=entry.entry_id, **account_device_info(coordinator))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Show vehicles "via" the account device.
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if device.id != account.id and device.via_device_id != account.id:
            registry.async_update_device(device.id, via_device_id=account.id)
    coordinator.async_start_stream()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: FmTrackConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FmTrackConfigEntry) -> bool:
    """Unload a config entry (the stream task is cancelled automatically)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
