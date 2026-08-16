"""Ship24 aggregator client - fourth and last link in the fallback chain.

Built against Ship24's public API (https://www.ship24.com):
``POST /public/v1/trackers`` to create a tracker for a number, then
``GET /public/v1/trackers/search/{trackingNumber}/results`` to poll it. Get
an API key at https://www.ship24.com/tracking-api.

Ship24 is the one aggregator here whose own status vocabulary
("statusMilestone") is already close to a one-to-one match with this
integration's normalized :class:`PackageStatus` values, so its mapping below
is the simplest of the four.
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

_CREATE_URL = "https://api.ship24.com/public/v1/trackers"
_RESULTS_URL = "https://api.ship24.com/public/v1/trackers/search/{tracking_number}/results"

# Ship24's "statusMilestone" -> normalized status.
# https://www.ship24.com/tracking-api/documentation
_STATUS_MAP: dict[str, PackageStatus] = {
    "pending": PackageStatus.INFO_RECEIVED,
    "info_received": PackageStatus.INFO_RECEIVED,
    "in_transit": PackageStatus.IN_TRANSIT,
    "out_for_delivery": PackageStatus.OUT_FOR_DELIVERY,
    "failed_attempt": PackageStatus.DELIVERY_EXCEPTION,
    "available_for_pickup": PackageStatus.AVAILABLE_FOR_PICKUP,
    "delivered": PackageStatus.DELIVERED,
    "exception": PackageStatus.DELIVERY_EXCEPTION,
    "expired": PackageStatus.DELIVERY_EXCEPTION,
}


class Ship24Backend(TrackingBackend):
    """Tracks packages via the Ship24 aggregator API."""

    carrier = CARRIER_AUTO
    source = "ship24"

    def __init__(self, session: aiohttp.ClientSession, *, api_key: str) -> None:
        self._session = session
        self._api_key = api_key
        self._registered: set[str] = set()

    async def async_track(self, tracking_number: str) -> TrackingResult:
        if tracking_number not in self._registered:
            await self._async_create(tracking_number)

        url = _RESULTS_URL.format(tracking_number=tracking_number)
        body = await self._async_request("GET", url)
        trackings = body.get("data", {}).get("trackings", [])

        if not trackings:
            return TrackingResult(
                status=PackageStatus.INFO_RECEIVED,
                status_detail="Registered with Ship24, waiting for first update",
                source=self.source,
                resolved_carrier=CARRIER_AUTO,
            )

        tracking = trackings[0]
        shipment = tracking.get("shipment", {})
        status = _STATUS_MAP.get(shipment.get("statusMilestone", ""), PackageStatus.UNKNOWN)

        events = [
            TrackingEvent(
                timestamp=_parse_ship24_datetime(raw_event.get("datetime")),
                description=raw_event.get("status") or "Unknown activity",
                location=raw_event.get("location"),
                status=_STATUS_MAP.get(raw_event.get("statusMilestone", ""), PackageStatus.IN_TRANSIT),
            )
            for raw_event in tracking.get("events", [])
        ]

        detail = events[0].description if events else "No activity yet"

        return TrackingResult(
            status=status,
            status_detail=detail,
            source=self.source,
            resolved_carrier=guess_carrier_from_name(shipment.get("carrierCode") or shipment.get("courierCode")),
            estimated_delivery=_parse_ship24_datetime(shipment.get("estimatedDeliveryDate")),
            events=tuple(events),
        )

    async def _async_create(self, tracking_number: str) -> None:
        try:
            await self._async_request("POST", _CREATE_URL, json={"trackingNumber": tracking_number})
        except TrackingBackendError:
            _LOGGER.debug("Ship24 create for %s failed or already existed; polling anyway", tracking_number)
        self._registered.add(tracking_number)

    async def _async_request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        request = self._session.get if method == "GET" else self._session.post
        async with request(url, headers=headers, **kwargs) as response:
            body: dict[str, Any] = await response.json(content_type=None)
            if response.status == 401 or response.status == 403:
                raise TrackingAuthError("Ship24 rejected the configured API key")
            if response.status >= 400:
                _LOGGER.debug("Ship24 request to %s failed (HTTP %s): %s", url, response.status, body)
                raise TrackingBackendError(f"Ship24 returned HTTP {response.status}")
        return body


def _parse_ship24_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
