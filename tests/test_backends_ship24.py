"""Tests for the Ship24 aggregator fallback backend."""

from __future__ import annotations

import pytest

from custom_components.package_tracker.backends.base import TrackingAuthError
from custom_components.package_tracker.backends.ship24 import Ship24Backend
from custom_components.package_tracker.const import CARRIER_FEDEX
from custom_components.package_tracker.models import PackageStatus

CREATE_OK = {"data": {"trackers": [{"trackerId": "abc123"}]}}
RESULTS_WITH_TRACKING = {
    "data": {
        "trackings": [
            {
                "shipment": {
                    "statusMilestone": "delivered",
                    "carrierCode": "fedex",
                    "estimatedDeliveryDate": "2026-08-05T18:00:00Z",
                },
                "events": [
                    {
                        "datetime": "2026-08-05T14:23:00Z",
                        "status": "Delivered",
                        "location": "Austin, TX",
                        "statusMilestone": "delivered",
                    },
                    {
                        "datetime": "2026-08-05T06:10:00Z",
                        "status": "Out for delivery",
                        "location": "Austin, TX",
                        "statusMilestone": "out_for_delivery",
                    },
                ],
            }
        ]
    }
}
RESULTS_EMPTY = {"data": {"trackings": []}}


async def test_creates_then_tracks_a_new_number(fake_session) -> None:
    fake_session.queue_json("POST", CREATE_OK)
    fake_session.queue_json("GET", RESULTS_WITH_TRACKING)
    backend = Ship24Backend(fake_session, api_key="key")

    result = await backend.async_track("123456789012")

    assert result.status == PackageStatus.DELIVERED
    assert result.resolved_carrier == CARRIER_FEDEX
    assert result.source == "ship24"
    assert len(result.events) == 2
    assert result.events[1].status == PackageStatus.OUT_FOR_DELIVERY
    assert result.estimated_delivery is not None
    assert len(fake_session.calls) == 2


async def test_does_not_recreate_an_already_seen_number(fake_session) -> None:
    fake_session.queue_json("POST", CREATE_OK)
    fake_session.queue_json("GET", RESULTS_WITH_TRACKING)
    fake_session.queue_json("GET", RESULTS_WITH_TRACKING)
    backend = Ship24Backend(fake_session, api_key="key")

    await backend.async_track("123456789012")
    await backend.async_track("123456789012")

    assert len(fake_session.calls) == 3


async def test_not_yet_resolved_number_reports_info_received(fake_session) -> None:
    fake_session.queue_json("POST", CREATE_OK)
    fake_session.queue_json("GET", RESULTS_EMPTY)
    backend = Ship24Backend(fake_session, api_key="key")

    result = await backend.async_track("123456789012")

    assert result.status == PackageStatus.INFO_RECEIVED


async def test_raises_auth_error_on_401(fake_session) -> None:
    fake_session.queue_json("POST", CREATE_OK)
    fake_session.queue_json("GET", {"error": "unauthorized"}, status=401)
    backend = Ship24Backend(fake_session, api_key="bad-key")

    with pytest.raises(TrackingAuthError):
        await backend.async_track("123456789012")
