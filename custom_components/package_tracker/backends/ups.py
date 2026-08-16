"""UPS Tracking API client.

Built against UPS's published Track API v1 (OAuth2 client-credentials grant,
then ``GET /api/track/v1/details/{trackingNumber}``). Register an app at
https://developer.ups.com to get a client ID/secret with Track API access.

UPS has changed response field names across API versions before and may do
so again; parsing here is defensive (``.get()`` throughout, one bounded
``try/except`` around the shape-critical lookups) so a drifted field shows up
as a loud, diagnosable error instead of a silent wrong answer.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Any

import aiohttp

from ..const import CARRIER_UPS
from ..models import PackageStatus, TrackingEvent, TrackingResult
from .base import TrackingBackend, TrackingBackendError
from .oauth import OAuthClientCredentials

_LOGGER = logging.getLogger(__name__)

_TOKEN_URL = "https://onlinetools.ups.com/security/v1/oauth/token"
_TRACK_URL = "https://onlinetools.ups.com/api/track/v1/details/{tracking_number}"

# UPS activity "status.type" codes -> normalized status.
# https://developer.ups.com/api/reference (Track API, Activity Status Type)
_STATUS_MAP: dict[str, PackageStatus] = {
    "D": PackageStatus.DELIVERED,
    "I": PackageStatus.IN_TRANSIT,
    "M": PackageStatus.INFO_RECEIVED,
    "O": PackageStatus.OUT_FOR_DELIVERY,
    "X": PackageStatus.DELIVERY_EXCEPTION,
    "P": PackageStatus.AVAILABLE_FOR_PICKUP,
    "RS": PackageStatus.RETURNED,
}


class UpsBackend(TrackingBackend):
    """Tracks packages via the official UPS Tracking API."""

    carrier = CARRIER_UPS
    source = "ups"

    def __init__(self, session: aiohttp.ClientSession, *, client_id: str, client_secret: str) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth = OAuthClientCredentials(session, token_url=_TOKEN_URL)

    async def async_track(self, tracking_number: str) -> TrackingResult:
        # Encoded by hand (rather than aiohttp.BasicAuth) so this doesn't
        # depend on an aiohttp version newer than what older supported Home
        # Assistant releases bundle.
        basic_auth = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        token = await self._oauth.async_get_token(
            headers={"Authorization": f"Basic {basic_auth}"},
            data={"grant_type": "client_credentials"},
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "transId": tracking_number,
            "transactionSrc": "home-assistant-package-tracker",
        }
        url = _TRACK_URL.format(tracking_number=tracking_number)
        async with self._session.get(url, headers=headers, params={"locale": "en_US"}) as response:
            body: dict[str, Any] = await response.json(content_type=None)
            if response.status >= 400:
                _LOGGER.debug("UPS tracking request for %s failed (HTTP %s): %s", tracking_number, response.status, body)
                raise TrackingBackendError(f"UPS returned HTTP {response.status} for {tracking_number}")

        try:
            shipment = body["trackResponse"]["shipment"][0]
            package = shipment["package"][0]
        except (KeyError, IndexError, TypeError) as err:
            _LOGGER.debug("UPS response for %s had an unexpected shape: %s", tracking_number, body)
            raise TrackingBackendError(f"UPS response for {tracking_number} had an unexpected shape") from err

        events = [
            TrackingEvent(
                timestamp=_parse_ups_datetime(activity.get("date"), activity.get("time")),
                description=activity.get("status", {}).get("description") or "Unknown activity",
                location=_format_ups_location(activity.get("location")),
                status=_STATUS_MAP.get(activity.get("status", {}).get("type", ""), PackageStatus.IN_TRANSIT),
            )
            for activity in package.get("activity", [])
        ]

        estimated_delivery = None
        for delivery_date in package.get("deliveryDate", []):
            if delivery_date.get("type") == "DEL":
                estimated_delivery = _parse_ups_datetime(delivery_date.get("date"), None)
                break

        return TrackingResult(
            status=events[0].status if events else PackageStatus.UNKNOWN,
            status_detail=events[0].description if events else "No activity yet",
            source=self.source,
            resolved_carrier=self.carrier,
            estimated_delivery=estimated_delivery,
            events=tuple(events),
        )


def _parse_ups_datetime(date: str | None, time_: str | None) -> datetime | None:
    """Parse UPS's ``YYYYMMDD``/``HHMMSS`` fields (carrier-local time, no timezone offset given)."""
    if not date:
        return None
    try:
        if time_:
            return datetime.strptime(f"{date}{time_}", "%Y%m%d%H%M%S")
        return datetime.strptime(date, "%Y%m%d")
    except ValueError:
        return None


def _format_ups_location(location: dict[str, Any] | None) -> str | None:
    if not location:
        return None
    address = location.get("address", {})
    parts = [address.get("city"), address.get("stateProvince"), address.get("country")]
    formatted = ", ".join(part for part in parts if part)
    return formatted or None
