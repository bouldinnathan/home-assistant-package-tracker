"""AfterShip aggregator client - second link in the fallback chain.

Built against AfterShip's classic v4 API (https://www.aftership.com),
which is what most third-party integrations still document:
``POST /v4/trackings`` to register a number, ``GET /v4/trackings`` filtered
by ``tracking_numbers`` to poll it. Get a free-tier API key at
https://www.aftership.com/api.

Like 17track, a freshly created tracking often isn't resolved yet on the
very next call - that's reported as ``PackageStatus.INFO_RECEIVED``, not an
error, exactly like the 17track backend.
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

_CREATE_URL = "https://api.aftership.com/v4/trackings"
_LIST_URL = "https://api.aftership.com/v4/trackings"

# AfterShip's "tag" field -> normalized status.
# https://www.aftership.com/docs/api/4/trackings
_STATUS_MAP: dict[str, PackageStatus] = {
    "Pending": PackageStatus.INFO_RECEIVED,
    "InfoReceived": PackageStatus.INFO_RECEIVED,
    "InTransit": PackageStatus.IN_TRANSIT,
    "OutForDelivery": PackageStatus.OUT_FOR_DELIVERY,
    "AttemptFail": PackageStatus.DELIVERY_EXCEPTION,
    "Delivered": PackageStatus.DELIVERED,
    "Exception": PackageStatus.DELIVERY_EXCEPTION,
    "Expired": PackageStatus.DELIVERY_EXCEPTION,
}


class AfterShipBackend(TrackingBackend):
    """Tracks packages via the AfterShip aggregator API."""

    carrier = CARRIER_AUTO
    source = "aftership"

    def __init__(self, session: aiohttp.ClientSession, *, api_key: str) -> None:
        self._session = session
        self._api_key = api_key
        self._registered: set[str] = set()

    async def async_track(self, tracking_number: str) -> TrackingResult:
        if tracking_number not in self._registered:
            await self._async_create(tracking_number)

        body = await self._async_request("GET", _LIST_URL, params={"tracking_numbers": tracking_number})
        trackings = body.get("data", {}).get("trackings", [])
        tracking = next((item for item in trackings if item.get("tracking_number") == tracking_number), None)

        if tracking is None:
            return TrackingResult(
                status=PackageStatus.INFO_RECEIVED,
                status_detail="Registered with AfterShip, waiting for first update",
                source=self.source,
                resolved_carrier=CARRIER_AUTO,
            )

        status = _STATUS_MAP.get(tracking.get("tag", ""), PackageStatus.UNKNOWN)
        events = [
            TrackingEvent(
                timestamp=_parse_aftership_datetime(checkpoint.get("checkpoint_time")),
                description=checkpoint.get("message") or "Unknown activity",
                location=_format_aftership_location(checkpoint),
                status=status if index == 0 else PackageStatus.IN_TRANSIT,
            )
            for index, checkpoint in enumerate(tracking.get("checkpoints", []))
        ]
        detail = events[0].description if events else tracking.get("subtag_message") or "No activity yet"

        return TrackingResult(
            status=status,
            status_detail=detail,
            source=self.source,
            resolved_carrier=guess_carrier_from_name(tracking.get("slug")),
            estimated_delivery=_parse_aftership_date(tracking.get("expected_delivery")),
            events=tuple(events),
        )

    async def _async_create(self, tracking_number: str) -> None:
        try:
            await self._async_request(
                "POST", _CREATE_URL, json={"tracking": {"tracking_number": tracking_number}}
            )
        except TrackingBackendError:
            # A 4xx here often just means "already exists" (AfterShip has no
            # idempotent upsert); either way, fall through to polling it.
            _LOGGER.debug("AfterShip create for %s failed or already existed; polling anyway", tracking_number)
        self._registered.add(tracking_number)

    async def _async_request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"aftership-api-key": self._api_key, "Content-Type": "application/json"}
        request = self._session.get if method == "GET" else self._session.post
        async with request(url, headers=headers, **kwargs) as response:
            body: dict[str, Any] = await response.json(content_type=None)
            if response.status == 401 or response.status == 403:
                raise TrackingAuthError("AfterShip rejected the configured API key")
            if response.status >= 400:
                _LOGGER.debug("AfterShip request to %s failed (HTTP %s): %s", url, response.status, body)
                raise TrackingBackendError(f"AfterShip returned HTTP {response.status}")
        return body


def _parse_aftership_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_aftership_date(value: str | None) -> datetime | None:
    return _parse_aftership_datetime(value)


def _format_aftership_location(checkpoint: dict[str, Any]) -> str | None:
    parts = [checkpoint.get("city"), checkpoint.get("state"), checkpoint.get("country_name")]
    formatted = ", ".join(part for part in parts if part)
    return formatted or checkpoint.get("location") or None
