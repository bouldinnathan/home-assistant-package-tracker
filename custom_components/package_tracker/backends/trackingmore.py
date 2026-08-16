"""TrackingMore aggregator client - third link in the fallback chain.

Built against TrackingMore's v4 API (https://www.trackingmore.com):
``POST /trackings/create`` to register a number (carrier omitted so
TrackingMore auto-detects it), ``GET /trackings/get`` filtered by
``tracking_numbers`` to poll it. Get a free-tier API key at
https://www.trackingmore.com/pricing.html.

TrackingMore's coarse status enum has no distinct "out for delivery" value,
so (like the DHL backend) this pattern-matches the latest event's
description for that milestone.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp

from ..const import CARRIER_AUTO
from ..models import PackageStatus, TrackingEvent, TrackingResult
from .base import TrackingAuthError, TrackingBackend, TrackingBackendError
from .carrier_names import guess_carrier_from_name

_LOGGER = logging.getLogger(__name__)

_CREATE_URL = "https://api.trackingmore.com/v4/trackings/create"
_GET_URL = "https://api.trackingmore.com/v4/trackings/get"

# TrackingMore's "status" field -> normalized status.
# https://www.trackingmore.com/tracking-api.html
_STATUS_MAP: dict[str, PackageStatus] = {
    "pending": PackageStatus.INFO_RECEIVED,
    "notfound": PackageStatus.UNKNOWN,
    "transit": PackageStatus.IN_TRANSIT,
    "pickup": PackageStatus.AVAILABLE_FOR_PICKUP,
    "delivered": PackageStatus.DELIVERED,
    "undelivered": PackageStatus.DELIVERY_EXCEPTION,
    "exception": PackageStatus.DELIVERY_EXCEPTION,
    "expired": PackageStatus.DELIVERY_EXCEPTION,
}
_OUT_FOR_DELIVERY_HINTS = ("out for delivery", "with courier", "on vehicle for delivery")


class TrackingMoreBackend(TrackingBackend):
    """Tracks packages via the TrackingMore aggregator API."""

    carrier = CARRIER_AUTO
    source = "trackingmore"

    def __init__(self, session: aiohttp.ClientSession, *, api_key: str) -> None:
        self._session = session
        self._api_key = api_key
        self._registered: set[str] = set()

    async def async_track(self, tracking_number: str) -> TrackingResult:
        if tracking_number not in self._registered:
            await self._async_create(tracking_number)

        body = await self._async_request("GET", _GET_URL, params={"tracking_numbers": tracking_number})
        items = body.get("data", [])
        item = next((entry for entry in items if entry.get("tracking_number") == tracking_number), None)

        if item is None:
            return TrackingResult(
                status=PackageStatus.INFO_RECEIVED,
                status_detail="Registered with TrackingMore, waiting for first update",
                source=self.source,
                resolved_carrier=CARRIER_AUTO,
            )

        raw_events = item.get("origin_info", {}).get("trackinfo", [])
        latest_description = ""
        if raw_events:
            latest_description = raw_events[0].get("StatusDescription") or raw_events[0].get("Details") or ""
        status = _resolve_status(item.get("status", ""), latest_description)

        events = [
            TrackingEvent(
                timestamp=_parse_trackingmore_datetime(raw_event.get("Date")),
                description=raw_event.get("StatusDescription") or raw_event.get("Details") or "Unknown activity",
                location=raw_event.get("Details")
                if raw_event.get("Details") != raw_event.get("StatusDescription")
                else None,
                status=status if index == 0 else PackageStatus.IN_TRANSIT,
            )
            for index, raw_event in enumerate(raw_events)
        ]

        detail = events[0].description if events else "No activity yet"

        return TrackingResult(
            status=status,
            status_detail=detail,
            source=self.source,
            resolved_carrier=guess_carrier_from_name(item.get("carrier_code")),
            estimated_delivery=_parse_trackingmore_date(item.get("scheduled_delivery_date")),
            events=tuple(events),
        )

    async def _async_create(self, tracking_number: str) -> None:
        try:
            await self._async_request("POST", _CREATE_URL, json={"tracking_number": tracking_number})
        except TrackingBackendError:
            _LOGGER.debug("TrackingMore create for %s failed or already existed; polling anyway", tracking_number)
        self._registered.add(tracking_number)

    async def _async_request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"Tracking-Api-Key": self._api_key, "Content-Type": "application/json"}
        request = self._session.get if method == "GET" else self._session.post
        async with request(url, headers=headers, **kwargs) as response:
            body: dict[str, Any] = await response.json(content_type=None)
            if response.status == 401 or response.status == 403:
                raise TrackingAuthError("TrackingMore rejected the configured API key")
            if response.status >= 400:
                _LOGGER.debug("TrackingMore request to %s failed (HTTP %s): %s", url, response.status, body)
                raise TrackingBackendError(f"TrackingMore returned HTTP {response.status}")
        return body


def _resolve_status(raw_status: str, latest_description: str) -> PackageStatus:
    if any(hint in latest_description.casefold() for hint in _OUT_FOR_DELIVERY_HINTS):
        return PackageStatus.OUT_FOR_DELIVERY
    return _STATUS_MAP.get(raw_status.casefold(), PackageStatus.UNKNOWN)


def _parse_trackingmore_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_trackingmore_date(value: str | None) -> datetime | None:
    return _parse_trackingmore_datetime(value)
