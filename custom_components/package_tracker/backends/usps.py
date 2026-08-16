"""USPS Tracking API client.

Built against USPS's current developer platform (api.usps.com), which uses
an OAuth2 client-credentials grant followed by
``GET /tracking/v3/tracking/{trackingNumber}``. Register an app at
https://developer.usps.com to get a client ID/secret with Tracking API
access. This is the successor to the older "Web Tools" XML API, which USPS
has been retiring - if your app still only has Web Tools credentials, it
won't work here.

See the module docstring in ``ups.py`` for the parsing-defensively rationale;
the same applies here.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import aiohttp

from ..const import CARRIER_USPS
from ..models import PackageStatus, TrackingEvent, TrackingResult
from .base import TrackingBackend, TrackingBackendError
from .oauth import OAuthClientCredentials

_LOGGER = logging.getLogger(__name__)

_TOKEN_URL = "https://api.usps.com/oauth2/v3/token"
_TRACK_URL = "https://api.usps.com/tracking/v3/tracking/{tracking_number}"

# USPS's "statusCategory" -> normalized status.
_STATUS_MAP: dict[str, PackageStatus] = {
    "delivered": PackageStatus.DELIVERED,
    "out for delivery": PackageStatus.OUT_FOR_DELIVERY,
    "in transit": PackageStatus.IN_TRANSIT,
    "accepted": PackageStatus.INFO_RECEIVED,
    "pre-shipment": PackageStatus.INFO_RECEIVED,
    "available for pickup": PackageStatus.AVAILABLE_FOR_PICKUP,
    "alert": PackageStatus.DELIVERY_EXCEPTION,
    "return to sender": PackageStatus.RETURNED,
}


class UspsBackend(TrackingBackend):
    """Tracks packages via the official USPS Tracking API."""

    carrier = CARRIER_USPS
    source = "usps"

    def __init__(self, session: aiohttp.ClientSession, *, client_id: str, client_secret: str) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth = OAuthClientCredentials(session, token_url=_TOKEN_URL)

    async def async_track(self, tracking_number: str) -> TrackingResult:
        token = await self._oauth.async_get_token(
            json={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            }
        )
        headers = {"Authorization": f"Bearer {token}"}
        url = _TRACK_URL.format(tracking_number=tracking_number)
        async with self._session.get(url, headers=headers) as response:
            body: dict[str, Any] = await response.json(content_type=None)
            if response.status >= 400:
                _LOGGER.debug(
                    "USPS tracking request for %s failed (HTTP %s): %s", tracking_number, response.status, body
                )
                raise TrackingBackendError(f"USPS returned HTTP {response.status} for {tracking_number}")

        if "trackingNumber" not in body:
            _LOGGER.debug("USPS response for %s had an unexpected shape: %s", tracking_number, body)
            raise TrackingBackendError(f"USPS response for {tracking_number} had an unexpected shape")

        events = [
            TrackingEvent(
                timestamp=_parse_usps_datetime(event.get("eventTimestamp")),
                description=event.get("eventType") or "Unknown activity",
                location=_format_usps_location(event),
                status=_STATUS_MAP.get((event.get("eventType") or "").casefold(), PackageStatus.IN_TRANSIT),
            )
            for event in body.get("trackingEvents", [])
        ]

        status = _STATUS_MAP.get((body.get("statusCategory") or "").casefold(), PackageStatus.UNKNOWN)
        detail = body.get("status") or body.get("statusSummary") or "No activity yet"

        return TrackingResult(
            status=status,
            status_detail=detail,
            source=self.source,
            resolved_carrier=self.carrier,
            estimated_delivery=_parse_usps_date(body.get("expectedDeliveryDate")),
            events=tuple(events),
        )


def _parse_usps_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_usps_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.combine(date.fromisoformat(value), datetime.min.time())
    except ValueError:
        return None


def _format_usps_location(event: dict[str, Any]) -> str | None:
    parts = [event.get("eventCity"), event.get("eventState"), event.get("eventCountry")]
    formatted = ", ".join(part for part in parts if part)
    return formatted or None
