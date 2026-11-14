"""Config flow for FM-Track."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import DEFAULT_BASE_URL, FmTrackApi, FmTrackAuthError, FmTrackError
from .const import CONF_BASE_URL, CONF_USE_STREAM, CONF_VEHICLES, DEFAULT_USE_STREAM, DOMAIN
from .parser import VehicleState


def _key_id(api_key: str) -> str:
    """Stable, non-reversible unique id for an API key."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def _label(state: VehicleState) -> str:
    parts = [state.name or state.object_id]
    if state.plate_number:
        parts.append(f"({state.plate_number})")
    return " ".join(parts)


class FmTrackConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FM-Track."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._vehicles: dict[str, VehicleState] = {}

    async def _validate(self, api_key: str, base_url: str) -> str | None:
        api = FmTrackApi(async_get_clientsession(self.hass), api_key, base_url)
        try:
            self._vehicles = await api.async_get_vehicles()
        except FmTrackAuthError:
            return "invalid_auth"
        except FmTrackError:
            return "cannot_connect"
        if not self._vehicles:
            return "no_vehicles"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
            await self.async_set_unique_id(_key_id(api_key))
            self._abort_if_unique_id_configured()
            if (error := await self._validate(api_key, base_url)) is None:
                self._data = {CONF_API_KEY: api_key, CONF_BASE_URL: base_url}
                return await self.async_step_vehicles()
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.URL)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_vehicles(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="FM-Track",
                data={**self._data, CONF_VEHICLES: user_input[CONF_VEHICLES]},
            )
        options = [
            SelectOptionDict(value=oid, label=_label(state))
            for oid, state in sorted(self._vehicles.items(), key=lambda i: _label(i[1]))
        ]
        return self.async_show_form(
            step_id="vehicles",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_VEHICLES, default=[o["value"] for o in options]): SelectSelector(
                        SelectSelectorConfig(options=options, multiple=True)
                    )
                }
            ),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            base_url = entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
            if (error := await self._validate(api_key, base_url)) is None:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=_key_id(api_key),
                    data_updates={CONF_API_KEY: api_key},
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> FmTrackOptionsFlow:
        return FmTrackOptionsFlow()


class FmTrackOptionsFlow(OptionsFlow):
    """Options: toggle the live stream."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USE_STREAM,
                        default=self.config_entry.options.get(CONF_USE_STREAM, DEFAULT_USE_STREAM),
                    ): bool
                }
            ),
        )
