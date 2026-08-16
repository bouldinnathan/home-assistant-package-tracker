"""17track.net aggregator client - fallback for carriers with no configured native API.

17track (https://www.17track.net) proxies tracking lookups for 1700+
carriers, including UPS/FedEx/DHL/USPS, behind one API key
(https://api.17track.net - register a free account to get a "17token" key).
Home Assistant's own built-in "17Track" integration is built on the same
service; this client only implements the two calls needed here: register a
number once, then poll its status.

17track needs a number "registered" before ``gettrackinfo`` returns anything
useful, and registration is not instant. A freshly registered number often
comes back as not-yet-accepted for the first poll cycle or two - that's
expected and reported as ``PackageStatus.INFO_RECEIVED``, not an error.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp

from ..const import CARRIER_AUTO, CARRIER_UNKNOWN
from ..models import PackageStatus, TrackingEvent, TrackingResult
from .base import TrackingAuthError, TrackingBackend, TrackingBackendError
from .carrier_names import guess_carrier_from_name

_LOGGER = logging.getLogger(__name__)

_REGISTER_URL = "https://api.17track.net/track/v2.2/register"
_TRACK_URL = "https://api.17track.net/track/v2.2/gettrackinfo"

# 17track's own normalized "latest_status.status" values.
# https://api.17track.net/en/doc?version=v2.2
_STATUS_MAP: dict[str, PackageStatus] = {
    "InfoReceived": PackageStatus.INFO_RECEIVED,
    "InTransit": PackageStatus.IN_TRANSIT,
    "OutForDelivery": PackageStatus.OUT_FOR_DELIVERY,
    "AvailableForPickup": PackageStatus.AVAILABLE_FOR_PICKUP,
    "Delivered": PackageStatus.DELIVERED,
    "DeliveryFailure": PackageStatus.DELIVERY_EXCEPTION,
    "Exception": PackageStatus.DELIVERY_EXCEPTION,
    "Expired": PackageStatus.DELIVERY_EXCEPTION,
    "NotFound": PackageStatus.UNKNOWN,
}


class SeventeenTrackBackend(TrackingBackend):
    """Tracks packages via the 17track.net aggregator API."""

    carrier = CARRIER_AUTO
    source = "seventeentrack"

    def __init__(self, session: aiohttp.ClientSession, *, api_key: str) -> None:
        self._session = session
        self._api_key = api_key
        self._registered: set[str] = set()

    async def async_track(self, tracking_number: str) -> TrackingResult:
        if tracking_number not in self._registered:
            await self._async_register(tracking_number)

        body = await self._async_post(_TRACK_URL, [{"number": tracking_number}])
        data = body.get("data", {})
        accepted = {entry.get("number"): entry for entry in data.get("accepted", [])}
        entry = accepted.get(tracking_number)

        if entry is None:
            # Registered but 17track hasn't processed it yet (or rejected it -
            # rejection reasons are logged at DEBUG for troubleshooting).
            for rejected in data.get("rejected", []):
                if rejected.get("number") == tracking_number:
                    _LOGGER.debug("17track rejected %s: %s", tracking_number, rejected)
            return TrackingResult(
                status=PackageStatus.INFO_RECEIVED,
                status_detail="Registered with 17track, waiting for first update",
                source=self.source,
                resolved_carrier=CARRIER_UNKNOWN,
            )

        track_info = entry.get("track_info", {})
        latest_status = track_info.get("latest_status", {}).get("status", "")
        status = _STATUS_MAP.get(latest_status, PackageStatus.UNKNOWN)

        events: list[TrackingEvent] = []
        providers = track_info.get("tracking", {}).get("providers", [])
        for provider in providers:
            for index, raw_event in enumerate(provider.get("events", [])):
                events.append(
                    TrackingEvent(
                        timestamp=_parse_17track_datetime(raw_event.get("time_iso")),
                        description=raw_event.get("description") or "Unknown activity",
                        location=raw_event.get("location") or None,
                        status=status if index == 0 else PackageStatus.IN_TRANSIT,
                    )
                )

        latest_event = track_info.get("latest_event", {})
        detail = latest_event.get("description") or (events[0].description if events else "No activity yet")

        estimated = track_info.get("time_metrics", {}).get("estimated_delivery_date", {})
        estimated_delivery = _parse_17track_datetime(estimated.get("to") or estimated.get("from"))

        return TrackingResult(
            status=status,
            status_detail=detail,
            source=self.source,
            resolved_carrier=guess_carrier_from_name(entry.get("carrier_name")),
            estimated_delivery=estimated_delivery,
            events=tuple(events),
        )

    async def _async_register(self, tracking_number: str) -> None:
        try:
            await self._async_post(_REGISTER_URL, [{"number": tracking_number}])
        except TrackingBackendError:
            # Registration failures (e.g. quota exhausted) shouldn't block a
            # gettrackinfo attempt - the number might already be registered
            # from a previous poll cycle before a restart cleared our cache.
            _LOGGER.warning("17track registration for %s failed; will still try to poll it", tracking_number)
        self._registered.add(tracking_number)

    async def _async_post(self, url: str, payload: list[dict[str, Any]]) -> dict[str, Any]:
        headers = {"17token": self._api_key, "Content-Type": "application/json"}
        async with self._session.post(url, headers=headers, json=payload) as response:
            body: dict[str, Any] = await response.json(content_type=None)
            if response.status == 401 or response.status == 403:
                raise TrackingAuthError("17track rejected the configured API key")
            if response.status >= 400:
                _LOGGER.debug("17track request to %s failed (HTTP %s): %s", url, response.status, body)
                raise TrackingBackendError(f"17track returned HTTP {response.status}")
        code = body.get("code")
        if code not in (0, None):
            _LOGGER.debug("17track request to %s returned error code %s: %s", url, code, body)
            raise TrackingBackendError(f"17track returned error code {code}")
        return body


def _parse_17track_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
