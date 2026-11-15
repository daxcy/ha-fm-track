"""Minimal async client for the FM-Track REST and streaming API."""

from __future__ import annotations

import asyncio
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
        """Raw responses of every other object-related API (diagnostics only).

        Used to find fields (such as an asset tracker's battery level) that
        the v2 records do not carry. Lists are cut to their last items.
        """
        oid = quote(object_id, safe="")
        now_dt = datetime.now(timezone.utc)
        now = iso(now_dt)
        frm = iso(since)
        calls: dict[str, tuple[str, dict[str, str]]] = {
            "object_v1": (f"/objects/{oid}", self._params(1)),
            "objects_list_v1": ("/objects", self._params(1)),
            "last_coordinate_single_v2": (f"/objects-last-coordinate/{oid}", self._params(2)),
            "last_coordinate_v3": (f"/objects-last-coordinate/{oid}", self._params(3)),
            "coordinates_v3": (
                f"/objects/{oid}/coordinates",
                self._params(3, from_datetime=frm, to_datetime=now, limit=5),
            ),
            "trips_v1": (
                f"/objects/{oid}/trips",
                self._params(1, from_datetime=frm, to_datetime=now, limit=1000),
            ),
            "detected_events_v1": (
                "/detected-events",
                self._params(1, object_id=object_id, from_datetime=frm, to_datetime=now, limit=1000),
            ),
            "fuel_events_v1": (
                "/fuel-events",
                self._params(1, object_id=object_id, from_datetime=frm, to_datetime=now, limit=1000),
            ),
            "ecodriving_object_v1": (
                "/ecodriving/object",
                self._params(1, id=object_id, from_datetime=frm, to_datetime=now),
            ),
            "countries_object_v1": (
                "/countries/object",
                self._params(1, id=object_id, from_datetime=frm, to_datetime=now),
            ),
            "events_v1": ("/events", self._params(1, limit=20)),
            "object_groups_v1": ("/object-groups", self._params(1, limit=20)),
        }
        result: dict[str, Any] = {}
        for name, (path, params) in calls.items():
            try:
                data = await self._get_json(path, params)
            except FmTrackError as err:
                result[name] = {"error": str(err)}
                continue
            result[name] = _shrink(data, object_id)
        result["coordinates_v1_scan"] = await self._scan_v1(oid, frm, now)
        result["stream_v1_first"] = await self._first_stream_message(1, object_id)
        result["stream_v2_first"] = await self._first_stream_message(2, object_id)
        return result

    async def _scan_v1(self, oid: str, frm: str, now: str) -> dict[str, Any]:
        """Every field of the v1 history that ever had a non-null value."""
        seen: dict[str, dict[str, Any]] = {}
        count = 0
        token: Any = None
        try:
            for _ in range(10):
                data = await self._get_json(
                    f"/objects/{oid}/coordinates",
                    self._params(1, fromDatetime=frm, toDatetime=now, limit=_PAGE_LIMIT, continuationToken=token),
                )
                if not isinstance(data, dict):
                    break
                for item in data.get("items") or []:
                    if not isinstance(item, dict):
                        continue
                    count += 1
                    for path, value in _walk(item):
                        if value is None:
                            continue
                        entry = seen.setdefault(path, {"count": 0, "first_seen": item.get("datetime")})
                        entry["count"] += 1
                        entry["last_seen"] = item.get("datetime")
                        entry["last"] = value
                new_token = data.get("continuation_token") or data.get("continuationToken")
                if not new_token or new_token == token:
                    break
                token = new_token
        except FmTrackError as err:
            return {"error": str(err), "records": count}
        return {"records": count, "fields": dict(sorted(seen.items()))}

    async def _first_stream_message(self, version: int, object_id: str) -> Any:
        """Connect to a stream version and return the first record (or a timeout note)."""
        try:
            async with asyncio.timeout(20):
                async with self._session.get(
                    f"{self._base_url}/object-coordinates-stream",
                    params=self._params(version, object_id=object_id),
                    headers={"Accept": "text/event-stream"},
                    timeout=aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=None),
                ) as resp:
                    self._check_status(resp.status)
                    lines: list[str] = []
                    async for raw_line in resp.content:
                        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                        if line.startswith("data:"):
                            lines.append(line[5:].lstrip())
                        elif not line and lines:
                            try:
                                return json.loads("\n".join(lines))
                            except ValueError:
                                return {"non_json": "\n".join(lines)[:2000]}
        except TimeoutError:
            return {"note": "no message within 20 s"}
        except FmTrackError as err:
            return {"error": str(err)}
        except aiohttp.ClientError as err:
            return {"error": type(err).__name__}
        return {"note": "stream closed without data"}

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


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Flatten nested dicts to (dotted.path, value) pairs."""
    if isinstance(value, dict):
        out: list[tuple[str, Any]] = []
        for key, sub in value.items():
            out.extend(_walk(sub, f"{prefix}{key}."))
        return out
    return [(prefix.rstrip("."), value)]


def _shrink(data: Any, object_id: str) -> Any:
    """Keep diagnostics small: last items of lists; only this object in object lists."""
    if isinstance(data, list):
        mine = [i for i in data if isinstance(i, dict) and object_id in (i.get("id"), i.get("object_id"))]
        return {"total": len(data), "items": mine or data[-3:]}
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            out[key] = _shrink(value, object_id) if isinstance(value, list) else value
        return out
    return data
