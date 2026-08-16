"""Tests for the UPS Tracking API backend."""

from __future__ import annotations

import pytest

from custom_components.package_tracker.backends.base import TrackingBackendError
from custom_components.package_tracker.backends.ups import UpsBackend
from custom_components.package_tracker.models import PackageStatus

TOKEN_BODY = {"access_token": "tok-123", "expires_in": 3600}
TRACK_BODY = {
    "trackResponse": {
        "shipment": [
            {
                "package": [
                    {
                        "activity": [
                            {
                                "status": {"type": "O", "description": "Out For Delivery"},
                                "date": "20260805",
                                "time": "081500",
                                "location": {"address": {"city": "Austin", "stateProvince": "TX", "country": "US"}},
                            },
                            {
                                "status": {"type": "I", "description": "Departed Facility"},
                                "date": "20260804",
                                "time": "220000",
                                "location": {"address": {"city": "Dallas", "stateProvince": "TX", "country": "US"}},
                            },
                        ],
                        "deliveryDate": [{"type": "DEL", "date": "20260805"}],
                    }
                ]
            }
        ]
    }
}


async def test_track_parses_latest_status_and_events(fake_session) -> None:
    fake_session.queue_json("POST", TOKEN_BODY)
    fake_session.queue_json("GET", TRACK_BODY)
    backend = UpsBackend(fake_session, client_id="id", client_secret="secret")

    result = await backend.async_track("1Z999AA10123456784")

    assert result.status == PackageStatus.OUT_FOR_DELIVERY
    assert result.status_detail == "Out For Delivery"
    assert result.resolved_carrier == "ups"
    assert result.source == "ups"
    assert len(result.events) == 2
    assert result.events[0].location == "Austin, TX, US"
    assert result.estimated_delivery is not None


async def test_track_raises_on_http_error(fake_session) -> None:
    fake_session.queue_json("POST", TOKEN_BODY)
    fake_session.queue_json("GET", {"response": {"errors": [{"message": "not found"}]}}, status=404)
    backend = UpsBackend(fake_session, client_id="id", client_secret="secret")

    with pytest.raises(TrackingBackendError):
        await backend.async_track("1Z999AA10123456784")


async def test_track_raises_on_unexpected_response_shape(fake_session) -> None:
    fake_session.queue_json("POST", TOKEN_BODY)
    fake_session.queue_json("GET", {"trackResponse": {}})
    backend = UpsBackend(fake_session, client_id="id", client_secret="secret")

    with pytest.raises(TrackingBackendError):
        await backend.async_track("1Z999AA10123456784")


async def test_token_is_cached_across_calls(fake_session) -> None:
    fake_session.queue_json("POST", TOKEN_BODY)
    fake_session.queue_json("GET", TRACK_BODY)
    fake_session.queue_json("GET", TRACK_BODY)
    backend = UpsBackend(fake_session, client_id="id", client_secret="secret")

    await backend.async_track("1Z999AA10123456784")
    await backend.async_track("1Z999AA10123456784")

    post_calls = [call for call in fake_session.calls if call[0] == "POST"]
    assert len(post_calls) == 1
