"""Tests for the USPS Tracking API backend."""

from __future__ import annotations

import pytest

from custom_components.package_tracker.backends.base import TrackingBackendError
from custom_components.package_tracker.backends.usps import UspsBackend
from custom_components.package_tracker.models import PackageStatus

TOKEN_BODY = {"access_token": "tok-123", "expires_in": 3600}
TRACK_BODY = {
    "trackingNumber": "9400111899223197428490",
    "statusCategory": "Out for Delivery",
    "status": "Out for Delivery",
    "expectedDeliveryDate": "2026-08-05",
    "trackingEvents": [
        {
            "eventType": "Out for Delivery",
            "eventTimestamp": "2026-08-05T08:00:00Z",
            "eventCity": "Austin",
            "eventState": "TX",
            "eventCountry": "US",
        },
        {
            "eventType": "In Transit",
            "eventTimestamp": "2026-08-04T20:00:00Z",
            "eventCity": "Dallas",
            "eventState": "TX",
            "eventCountry": "US",
        },
    ],
}


async def test_track_parses_latest_status_and_events(fake_session) -> None:
    fake_session.queue_json("POST", TOKEN_BODY)
    fake_session.queue_json("GET", TRACK_BODY)
    backend = UspsBackend(fake_session, client_id="id", client_secret="secret")

    result = await backend.async_track("9400111899223197428490")

    assert result.status == PackageStatus.OUT_FOR_DELIVERY
    assert result.resolved_carrier == "usps"
    assert len(result.events) == 2
    assert result.events[0].location == "Austin, TX, US"
    assert result.estimated_delivery is not None


async def test_track_raises_on_http_error(fake_session) -> None:
    fake_session.queue_json("POST", TOKEN_BODY)
    fake_session.queue_json("GET", {"error": "not found"}, status=404)
    backend = UspsBackend(fake_session, client_id="id", client_secret="secret")

    with pytest.raises(TrackingBackendError):
        await backend.async_track("9400111899223197428490")


async def test_track_raises_on_unexpected_response_shape(fake_session) -> None:
    fake_session.queue_json("POST", TOKEN_BODY)
    fake_session.queue_json("GET", {"unexpected": True})
    backend = UspsBackend(fake_session, client_id="id", client_secret="secret")

    with pytest.raises(TrackingBackendError):
        await backend.async_track("9400111899223197428490")
