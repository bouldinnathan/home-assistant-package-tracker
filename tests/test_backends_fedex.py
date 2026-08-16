"""Tests for the FedEx Track API backend."""

from __future__ import annotations

import pytest

from custom_components.package_tracker.backends.base import TrackingBackendError
from custom_components.package_tracker.backends.fedex import FedexBackend
from custom_components.package_tracker.models import PackageStatus

TOKEN_BODY = {"access_token": "tok-123", "expires_in": 3600}
TRACK_BODY = {
    "output": {
        "completeTrackResults": [
            {
                "trackResults": [
                    {
                        "latestStatusDetail": {"derivedCode": "DL", "description": "Delivered"},
                        "dateAndTimes": [
                            {"type": "ESTIMATED_DELIVERY", "dateTime": "2026-08-05T18:00:00-05:00"},
                        ],
                        "scanEvents": [
                            {
                                "date": "2026-08-05T14:23:00-05:00",
                                "eventType": "DL",
                                "eventDescription": "Delivered",
                                "scanLocation": {"city": "Austin", "stateOrProvinceCode": "TX", "countryCode": "US"},
                            },
                            {
                                "date": "2026-08-05T06:10:00-05:00",
                                "eventType": "OD",
                                "eventDescription": "Out for delivery",
                                "scanLocation": {"city": "Austin", "stateOrProvinceCode": "TX", "countryCode": "US"},
                            },
                        ],
                    }
                ]
            }
        ]
    }
}


async def test_track_parses_latest_status_and_events(fake_session) -> None:
    fake_session.queue_json("POST", TOKEN_BODY)
    fake_session.queue_json("POST", TRACK_BODY)
    backend = FedexBackend(fake_session, client_id="id", client_secret="secret")

    result = await backend.async_track("123456789012")

    assert result.status == PackageStatus.DELIVERED
    assert result.status_detail == "Delivered"
    assert result.resolved_carrier == "fedex"
    assert len(result.events) == 2
    assert result.events[0].status == PackageStatus.DELIVERED
    assert result.events[1].status == PackageStatus.OUT_FOR_DELIVERY
    assert result.estimated_delivery is not None


async def test_track_raises_on_http_error(fake_session) -> None:
    fake_session.queue_json("POST", TOKEN_BODY)
    fake_session.queue_json("POST", {"errors": [{"message": "bad request"}]}, status=400)
    backend = FedexBackend(fake_session, client_id="id", client_secret="secret")

    with pytest.raises(TrackingBackendError):
        await backend.async_track("123456789012")


async def test_track_raises_on_unexpected_response_shape(fake_session) -> None:
    fake_session.queue_json("POST", TOKEN_BODY)
    fake_session.queue_json("POST", {"output": {}})
    backend = FedexBackend(fake_session, client_id="id", client_secret="secret")

    with pytest.raises(TrackingBackendError):
        await backend.async_track("123456789012")
