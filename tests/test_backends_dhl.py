"""Tests for the DHL Unified Tracking API backend."""

from __future__ import annotations

import pytest

from custom_components.package_tracker.backends.base import TrackingBackendError
from custom_components.package_tracker.backends.dhl import DhlBackend
from custom_components.package_tracker.models import PackageStatus

TRACK_BODY = {
    "shipments": [
        {
            "status": {"statusCode": "transit", "description": "With delivery courier"},
            "estimatedTimeOfDelivery": "2026-08-05T18:00:00Z",
            "events": [
                {
                    "timestamp": "2026-08-05T08:00:00Z",
                    "statusCode": "transit",
                    "description": "With delivery courier",
                    "location": {"address": {"addressLocality": "Austin", "countryCode": "US"}},
                },
                {
                    "timestamp": "2026-08-04T20:00:00Z",
                    "statusCode": "transit",
                    "description": "Processed at facility",
                    "location": {"address": {"addressLocality": "Dallas", "countryCode": "US"}},
                },
            ],
        }
    ]
}


async def test_track_parses_status_with_out_for_delivery_text_override(fake_session) -> None:
    fake_session.queue_json("GET", TRACK_BODY)
    backend = DhlBackend(fake_session, api_key="key")

    result = await backend.async_track("1234567890")

    # DHL's coarse statusCode enum has no "out for delivery" value; the
    # backend upgrades it based on the free-text description instead.
    assert result.status == PackageStatus.OUT_FOR_DELIVERY
    assert result.resolved_carrier == "dhl"
    assert len(result.events) == 2
    assert result.events[0].location == "Austin, US"
    assert result.estimated_delivery is not None


async def test_track_raises_on_http_error(fake_session) -> None:
    fake_session.queue_json("GET", {"detail": "unauthorized"}, status=401)
    backend = DhlBackend(fake_session, api_key="bad-key")

    with pytest.raises(TrackingBackendError):
        await backend.async_track("1234567890")


async def test_track_raises_on_unexpected_response_shape(fake_session) -> None:
    fake_session.queue_json("GET", {"shipments": []})
    backend = DhlBackend(fake_session, api_key="key")

    with pytest.raises(TrackingBackendError):
        await backend.async_track("1234567890")
