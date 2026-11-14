"""Minimal async client for the FM-Track REST and streaming API."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from .parser import VehicleState, iter_stream_objects, parse_object

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.fm-track.com"
_PAGE_LIMIT = 1000


class FmTrackError(Exception):
    """Base error."""


class FmTrackAuthError(FmTrackError):
    """API key missing, invalid or not allowed."""


class FmTrackConnectionError(FmTrackError):
    """Network or server problem."""


class FmTrackApi:
    """FM-Track API client.

    The API key travels as a query parameter, so URLs and aiohttp exception
    texts (which contain the URL) are never logged or re-raised verbatim.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def _params(self, version: int, **extra: Any) -> dict[str, str]:
        params = {"version": str(version), "api_key": self._api_key}
        params.update({k: str(v) for k, v in extra.items() if v is not None})
        return params

    @staticmethod
    def _check_status(status: int) -> None:
        if status in (401, 403):
            raise FmTrackAuthError(f"HTTP {status}")
        if status >= 400:
            raise FmTrackConnectionError(f"HTTP {status}")

    async def _get_json(self, path: str, params: dict[str, str]) -> Any:
        try:
            async with self._session.get(
                f"{self._base_url}{path}",
                params=params,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                self._check_status(resp.status)
                return await resp.json(content_type=None)
        except FmTrackError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise FmTrackConnectionError(type(err).__name__) from None

    async def async_get_vehicles(self) -> dict[str, VehicleState]:
        """Return all objects with their last coordinate (v2), following pagination."""
        vehicles: dict[str, VehicleState] = {}
        token: str | None = None
        while True:
            data = await self._get_json(
                "/objects-last-coordinate",
                self._params(2, limit=_PAGE_LIMIT, continuation_token=token),
            )
            if not isinstance(data, dict):
                raise FmTrackConnectionError("Unexpected response")
            for raw in data.get("results") or []:
                if isinstance(raw, dict) and (state := parse_object(raw)):
                    vehicles[state.object_id] = state
            new_token = data.get("continuation_token")
            if not new_token or new_token == token:
                return vehicles
            token = new_token

    async def async_stream(self, object_id: str | None = None) -> AsyncIterator[VehicleState]:
        """Yield updates from the Object Coordinates Streaming API v2 (SSE).

        Returns when the server closes the connection (it does so after 4 hours
        without new records); the caller is responsible for reconnecting.
        """
        try:
            async with self._session.get(
                f"{self._base_url}/object-coordinates-stream",
                params=self._params(2, object_id=object_id),
                headers={"Accept": "text/event-stream"},
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None),
            ) as resp:
                self._check_status(resp.status)
                data_lines: list[str] = []
                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                        continue
                    if line or not data_lines:
                        continue  # comments, event:/id: lines, keep-alives
                    payload = "\n".join(data_lines)
                    data_lines = []
                    try:
                        decoded = json.loads(payload)
                    except ValueError:
                        _LOGGER.debug("Ignoring non-JSON stream payload")
                        continue
                    for raw in iter_stream_objects(decoded):
                        if state := parse_object(raw):
                            yield state
        except FmTrackError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise FmTrackConnectionError(type(err).__name__) from None
