"""DHL Unified Tracking API client.

Built against DHL's published Unified Tracking API
(``GET /track/shipments``), which covers DHL Express, eCommerce, and Parcel
shipments with a single flat API key - no OAuth handshake needed. Register
an app at https://developer.dhl.com to get a key with tracking access.

See the module docstring in ``ups.py`` for the parsing-defensively rationale;
the same applies here.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp

from ..const import CARRIER_DHL
from ..models import PackageStatus, TrackingEvent, TrackingResult
from .base import TrackingBackend, TrackingBackendError

_LOGGER = logging.getLogger(__name__)

_TRACK_URL = "https://api-eu.dhl.com/track/shipments"

# DHL's coarse "status.statusCode" enum -> normalized status. DHL doesn't
# distinguish "out for delivery" at this enum level, so async_track()
# pattern-matches the free-text description for that milestone as well.
_STATUS_MAP: dict[str, PackageStatus] = {
    "pre-transit": PackageStatus.INFO_RECEIVED,
    "transit": PackageStatus.IN_TRANSIT,
    "delivered": PackageStatus.DELIVERED,
    "failure": PackageStatus.DELIVERY_EXCEPTION,
    "unknown": PackageStatus.UNKNOWN,
}
_OUT_FOR_DELIVERY_HINTS = ("out for delivery", "with delivery courier", "on vehicle for delivery")


class DhlBackend(TrackingBackend):
    """Tracks packages via the official DHL Unified Tracking API."""

    carrier = CARRIER_DHL
    source = "dhl"

    def __init__(self, session: aiohttp.ClientSession, *, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    async def async_track(self, tracking_number: str) -> TrackingResult:
        headers = {"DHL-API-Key": self._api_key}
        params = {"trackingNumber": tracking_number}
        async with self._session.get(_TRACK_URL, headers=headers, params=params) as response:
            body: dict[str, Any] = await response.json(content_type=None)
            if response.status >= 400:
                _LOGGER.debug(
                    "DHL tracking request for %s failed (HTTP %s): %s", tracking_number, response.status, body
                )
                raise TrackingBackendError(f"DHL returned HTTP {response.status} for {tracking_number}")

        try:
            shipment = body["shipments"][0]
        except (KeyError, IndexError, TypeError) as err:
            _LOGGER.debug("DHL response for %s had an unexpected shape: %s", tracking_number, body)
            raise TrackingBackendError(f"DHL response for {tracking_number} had an unexpected shape") from err

        events = [
            TrackingEvent(
                timestamp=_parse_dhl_datetime(event.get("timestamp")),
                description=event.get("description") or "Unknown activity",
                location=_format_dhl_location(event.get("location")),
                status=_dhl_event_status(event),
            )
            for event in shipment.get("events", [])
        ]

        status_block = shipment.get("status", {})
        status = _dhl_event_status(status_block)
        detail = status_block.get("description") or (events[0].description if events else "No activity yet")

        return TrackingResult(
            status=status,
            status_detail=detail,
            source=self.source,
            resolved_carrier=self.carrier,
            estimated_delivery=_parse_dhl_datetime(shipment.get("estimatedTimeOfDelivery")),
            events=tuple(events),
        )


def _dhl_event_status(entry: dict[str, Any]) -> PackageStatus:
    description = (entry.get("description") or entry.get("status") or "").casefold()
    if any(hint in description for hint in _OUT_FOR_DELIVERY_HINTS):
        return PackageStatus.OUT_FOR_DELIVERY
    return _STATUS_MAP.get((entry.get("statusCode") or "").casefold(), PackageStatus.IN_TRANSIT)


def _parse_dhl_datetime(value: str | None) -> datetime | None:
    """Parse DHL's ISO-8601 timestamps, which normally include a UTC offset."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_dhl_location(location: dict[str, Any] | None) -> str | None:
    if not location:
        return None
    address = location.get("address", {})
    parts = [address.get("addressLocality"), address.get("countryCode")]
    formatted = ", ".join(part for part in parts if part)
    return formatted or None
