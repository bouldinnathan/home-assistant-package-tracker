"""FedEx Track API client.

Built against FedEx's published Track API v1 (OAuth2 client-credentials
grant, then ``POST /track/v1/trackingnumbers``). Register an app at
https://developer.fedex.com to get a client ID/secret with Track API access.

See the module docstring in ``ups.py`` for the parsing-defensively rationale;
the same applies here.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp

from ..const import CARRIER_FEDEX
from ..models import PackageStatus, TrackingEvent, TrackingResult
from .base import TrackingBackend, TrackingBackendError
from .oauth import OAuthClientCredentials

_LOGGER = logging.getLogger(__name__)

_TOKEN_URL = "https://apis.fedex.com/oauth/token"
_TRACK_URL = "https://apis.fedex.com/track/v1/trackingnumbers"

# FedEx scan event type codes -> normalized status. FedEx documents dozens of
# fine-grained codes; unrecognized ones fall back to IN_TRANSIT rather than
# UNKNOWN, since by far the most common case is "some transit milestone we
# haven't special-cased yet," not "package status is unknown."
_STATUS_MAP: dict[str, PackageStatus] = {
    "DL": PackageStatus.DELIVERED,
    "OD": PackageStatus.OUT_FOR_DELIVERY,
    "DE": PackageStatus.DELIVERY_EXCEPTION,
    "CA": PackageStatus.DELIVERY_EXCEPTION,
    "RS": PackageStatus.RETURNED,
    "HL": PackageStatus.AVAILABLE_FOR_PICKUP,
    "PU": PackageStatus.IN_TRANSIT,
    "IT": PackageStatus.IN_TRANSIT,
    "AR": PackageStatus.IN_TRANSIT,
    "DP": PackageStatus.IN_TRANSIT,
    "OC": PackageStatus.INFO_RECEIVED,
}


class FedexBackend(TrackingBackend):
    """Tracks packages via the official FedEx Track API."""

    carrier = CARRIER_FEDEX
    source = "fedex"

    def __init__(self, session: aiohttp.ClientSession, *, client_id: str, client_secret: str) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth = OAuthClientCredentials(session, token_url=_TOKEN_URL)

    async def async_track(self, tracking_number: str) -> TrackingResult:
        token = await self._oauth.async_get_token(
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "X-locale": "en_US",
            "Content-Type": "application/json",
        }
        payload = {
            "trackingInfo": [{"trackingNumberInfo": {"trackingNumber": tracking_number}}],
            "includeDetailedScans": True,
        }
        async with self._session.post(_TRACK_URL, headers=headers, json=payload) as response:
            body: dict[str, Any] = await response.json(content_type=None)
            if response.status >= 400:
                _LOGGER.debug(
                    "FedEx tracking request for %s failed (HTTP %s): %s", tracking_number, response.status, body
                )
                raise TrackingBackendError(f"FedEx returned HTTP {response.status} for {tracking_number}")

        try:
            complete_results = body["output"]["completeTrackResults"][0]["trackResults"][0]
        except (KeyError, IndexError, TypeError) as err:
            _LOGGER.debug("FedEx response for %s had an unexpected shape: %s", tracking_number, body)
            raise TrackingBackendError(f"FedEx response for {tracking_number} had an unexpected shape") from err

        events = [
            TrackingEvent(
                timestamp=_parse_fedex_datetime(scan.get("date")),
                description=scan.get("eventDescription") or "Unknown activity",
                location=_format_fedex_location(scan.get("scanLocation")),
                status=_STATUS_MAP.get(scan.get("eventType", ""), PackageStatus.IN_TRANSIT),
            )
            for scan in complete_results.get("scanEvents", [])
        ]

        estimated_delivery = None
        for date_and_time in complete_results.get("dateAndTimes", []):
            if date_and_time.get("type") == "ESTIMATED_DELIVERY":
                estimated_delivery = _parse_fedex_datetime(date_and_time.get("dateTime"))
                break

        latest = complete_results.get("latestStatusDetail", {})
        latest_code = latest.get("derivedCode") or latest.get("code") or ""
        status = _STATUS_MAP.get(latest_code, events[0].status if events else PackageStatus.UNKNOWN)
        detail = latest.get("description") or (events[0].description if events else "No activity yet")

        return TrackingResult(
            status=status,
            status_detail=detail,
            source=self.source,
            resolved_carrier=self.carrier,
            estimated_delivery=estimated_delivery,
            events=tuple(events),
        )


def _parse_fedex_datetime(value: str | None) -> datetime | None:
    """Parse FedEx's ISO-8601 timestamps, which normally include a UTC offset."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_fedex_location(location: dict[str, Any] | None) -> str | None:
    if not location:
        return None
    parts = [location.get("city"), location.get("stateOrProvinceCode"), location.get("countryCode")]
    formatted = ", ".join(part for part in parts if part)
    return formatted or None
