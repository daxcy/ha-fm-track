"""Minimal async client for the FM-Track REST and streaming API."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import aiohttp

from .parser import Trip, VehicleState, iter_stream_objects, parse_object, parse_trip

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.fm-track.com"
_PAGE_LIMIT = 1000
_MAX_PAGES = 20


class FmTrackError(Exception):
    """Base error."""


class FmTrackAuthError(FmTrackError):
    """API key missing or invalid (HTTP 401)."""


class FmTrackForbiddenError(FmTrackError):
    """The key is valid but this API is not part of the plan (HTTP 403/404)."""

    def __init__(self, message: str, status: int = 403) -> None:
        super().__init__(message)
        self.status = status


class FmTrackConnectionError(FmTrackError):
    """Network or server problem."""


def iso(dt: datetime) -> str:
    """Format a datetime the way the API expects (UTC, milliseconds, Z)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


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
        for key, value in extra.items():
            if value is None:
                continue
            params[key] = str(value).lower() if isinstance(value, bool) else str(value)
        return params

    @staticmethod
    def _check_status(status: int) -> None:
        if status == 401:
            raise FmTrackAuthError("HTTP 401")
        if status in (403, 404):
            raise FmTrackForbiddenError(f"HTTP {status}", status)
        if status == 429:
            raise FmTrackConnectionError("HTTP 429 (rate limited)")
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

    # --- objects ---------------------------------------------------------

    async def async_get_vehicles(self) -> dict[str, VehicleState]:
        """All objects with their last coordinate (v2), following pagination."""
        raw = await self.async_get_vehicles_raw()
        vehicles: dict[str, VehicleState] = {}
        for item in raw:
            if state := parse_object(item):
                vehicles[state.object_id] = state
        return vehicles

    async def async_get_vehicles_raw(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        token: str | None = None
        for _ in range(_MAX_PAGES):
            data = await self._get_json(
                "/objects-last-coordinate",
                self._params(2, limit=_PAGE_LIMIT, continuation_token=token),
            )
            if not isinstance(data, dict):
                raise FmTrackConnectionError("Unexpected response")
            results.extend(r for r in data.get("results") or [] if isinstance(r, dict))
            new_token = data.get("continuation_token")
            if not new_token or new_token == token:
                break
            token = new_token
        return results

    async def async_get_record(self, object_id: str, datetime_raw: str) -> dict[str, Any] | None:
        """Full history record (all inputs, geozones, tyres) at an exact timestamp."""
        data = await self._get_json(
            f"/objects/{quote(object_id, safe='')}/coordinates/{quote(datetime_raw, safe='')}",
            self._params(2, include_geozones=True, include_tire_parameters=True),
        )
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            items = [i for i in data["items"] if isinstance(i, dict)]
            return items[-1] if items else None
        return data if isinstance(data, dict) else None

    async def async_get_records(self, object_id: str, since: datetime, max_pages: int = 5) -> list[dict[str, Any]]:
        """All history records in [since, now] (bounded by max_pages)."""
        records: list[dict[str, Any]] = []
        token: str | None = None
        for _ in range(max_pages):
            data = await self._get_json(
                f"/objects/{quote(object_id, safe='')}/coordinates",
                self._params(
                    2,
                    from_datetime=iso(since),
                    to_datetime=iso(datetime.now(timezone.utc)),
                    limit=_PAGE_LIMIT,
                    continuation_token=token,
                ),
            )
            if not isinstance(data, dict):
                break
            records.extend(i for i in data.get("items") or [] if isinstance(i, dict))
            new_token = data.get("continuation_token")
            if not new_token or new_token == token:
                break
            token = new_token
        return records

    async def async_get_latest_record(self, object_id: str, since: datetime) -> dict[str, Any] | None:
        """Most recent history record in [since, now]; fallback when the exact lookup fails."""
        latest: dict[str, Any] | None = None
        token: str | None = None
        for _ in range(_MAX_PAGES):
            data = await self._get_json(
                f"/objects/{quote(object_id, safe='')}/coordinates",
                self._params(
                    2,
                    from_datetime=iso(since),
                    to_datetime=iso(datetime.now(timezone.utc)),
                    limit=_PAGE_LIMIT,
                    continuation_token=token,
                    include_geozones=True,
                    include_tire_parameters=True,
                ),
            )
            if not isinstance(data, dict):
                break
            for item in data.get("items") or []:
                if isinstance(item, dict) and (
                    latest is None or str(item.get("datetime", "")) >= str(latest.get("datetime", ""))
                ):
                    latest = item
            new_token = data.get("continuation_token")
            if not new_token or new_token == token:
                break
            token = new_token
        return latest

    async def async_probe(self, object_id: str, since: datetime) -> dict[str, Any]:
        """Raw responses of other API versions for one object (diagnostics only)."""
        oid = quote(object_id, safe="")
        now = iso(datetime.now(timezone.utc))
        calls = {
            "object_v1": (f"/objects/{oid}", self._params(1)),
            "last_coordinate_v3": (
                f"/objects-last-coordinate/{oid}",
                self._params(3),
            ),
            "coordinates_v1": (
                f"/objects/{oid}/coordinates",
                self._params(1, fromDatetime=iso(since), toDatetime=now, limit=5),
            ),
            "coordinates_v3": (
                f"/objects/{oid}/coordinates",
                self._params(3, from_datetime=iso(since), to_datetime=now, limit=5),
            ),
        }
        result: dict[str, Any] = {}
        for name, (path, params) in calls.items():
            try:
                data = await self._get_json(path, params)
            except FmTrackError as err:
                result[name] = {"error": str(err)}
                continue
            if isinstance(data, dict):
                for key in ("items", "coordinates", "results"):
                    if isinstance(data.get(key), list):
                        data = {**data, key: data[key][-2:]}
            result[name] = data
        return result

    # --- trips, events, geozones ----------------------------------------

    async def async_get_trips(self, object_id: str, since: datetime) -> list[Trip]:
        trips: list[Trip] = []
        token: str | None = None
        for _ in range(_MAX_PAGES):
            data = await self._get_json(
                f"/objects/{quote(object_id, safe='')}/trips",
                self._params(
                    1,
                    from_datetime=iso(since),
                    to_datetime=iso(datetime.now(timezone.utc)),
                    limit=_PAGE_LIMIT,
                    continuation_token=token,
                ),
            )
            if not isinstance(data, dict):
                break
            for raw in data.get("trips") or []:
                if trip := parse_trip(raw):
                    trip.object_id = trip.object_id or object_id
                    trips.append(trip)
            new_token = data.get("continuation_token")
            if not new_token or new_token == token:
                break
            token = new_token
        return trips

    async def async_get_detected_events(
        self, object_id: str, since: datetime, until: datetime
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        token: Any = None
        for _ in range(_MAX_PAGES):
            data = await self._get_json(
                "/detected-events",
                self._params(
                    1,
                    object_id=object_id,
                    from_datetime=iso(since),
                    to_datetime=iso(until),
                    limit=_PAGE_LIMIT,
                    continuation_token=token,
                ),
            )
            if not isinstance(data, dict):
                break
            events.extend(e for e in data.get("events") or [] if isinstance(e, dict))
            new_token = data.get("continuation_token")
            if new_token in (None, "") or new_token == token:
                break
            token = new_token
        return events

    async def async_get_geozones(self) -> dict[str, str]:
        """Map of geozone id → name."""
        zones: dict[str, str] = {}
        token: Any = None
        for _ in range(_MAX_PAGES):
            data = await self._get_json(
                "/geozones",
                self._params(1, limit=_PAGE_LIMIT, continuation_token=token, include_geometry=False),
            )
            if not isinstance(data, dict):
                break
            for zone in data.get("items") or []:
                if isinstance(zone, dict) and zone.get("id"):
                    zones[str(zone["id"])] = zone.get("name") or str(zone["id"])
            new_token = data.get("continuation_token")
            if new_token in (None, "") or new_token == token:
                break
            token = new_token
        return zones

    # --- streaming -------------------------------------------------------

    async def async_stream(
        self,
        object_id: str | None = None,
        on_connect: Callable[[], None] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield raw records from the Object Coordinates Streaming API v2 (SSE).

        Returns when the server closes the connection (it does so after 4 hours
        without new records); the caller is responsible for reconnecting.
        """
        try:
            async with self._session.get(
                f"{self._base_url}/object-coordinates-stream",
                params=self._params(
                    2, object_id=object_id, include_geozones=True, include_tire_parameters=True
                ),
                headers={"Accept": "text/event-stream"},
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None),
            ) as resp:
                self._check_status(resp.status)
                if on_connect:
                    on_connect()
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
                        yield raw
        except FmTrackError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise FmTrackConnectionError(type(err).__name__) from None
