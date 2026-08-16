"""Tests for the TrackingMore aggregator fallback backend."""

from __future__ import annotations

import pytest

from custom_components.package_tracker.backends.base import TrackingAuthError
from custom_components.package_tracker.backends.trackingmore import TrackingMoreBackend
from custom_components.package_tracker.models import PackageStatus

CREATE_OK = {"meta": {"code": 200}, "data": {"tracking_number": "1234567890"}}
GET_WITH_RESULT = {
    "meta": {"code": 200},
    "data": [
        {
            "tracking_number": "1234567890",
            "status": "transit",
            "carrier_code": "dhl",
            "scheduled_delivery_date": "2026-08-06",
            "origin_info": {
                "trackinfo": [
                    {"Date": "2026-08-05T08:00:00Z", "StatusDescription": "Out for delivery", "Details": "Austin, TX"},
                    {"Date": "2026-08-04T20:00:00Z", "StatusDescription": "In transit", "Details": "Dallas, TX"},
                ]
            },
        }
    ],
}
GET_EMPTY = {"meta": {"code": 200}, "data": []}


async def test_creates_then_tracks_a_new_number(fake_session) -> None:
    fake_session.queue_json("POST", CREATE_OK)
    fake_session.queue_json("GET", GET_WITH_RESULT)
    backend = TrackingMoreBackend(fake_session, api_key="key")

    result = await backend.async_track("1234567890")

    # "transit" plus a latest-event description containing "out for
    # delivery" upgrades the coarse status, same trick the DHL backend uses.
    assert result.status == PackageStatus.OUT_FOR_DELIVERY
    assert result.resolved_carrier == "dhl"
    assert result.source == "trackingmore"
    assert len(result.events) == 2
    assert result.estimated_delivery is not None
    assert len(fake_session.calls) == 2


async def test_does_not_recreate_an_already_seen_number(fake_session) -> None:
    fake_session.queue_json("POST", CREATE_OK)
    fake_session.queue_json("GET", GET_WITH_RESULT)
    fake_session.queue_json("GET", GET_WITH_RESULT)
    backend = TrackingMoreBackend(fake_session, api_key="key")

    await backend.async_track("1234567890")
    await backend.async_track("1234567890")

    assert len(fake_session.calls) == 3


async def test_not_yet_resolved_number_reports_info_received(fake_session) -> None:
    fake_session.queue_json("POST", CREATE_OK)
    fake_session.queue_json("GET", GET_EMPTY)
    backend = TrackingMoreBackend(fake_session, api_key="key")

    result = await backend.async_track("1234567890")

    assert result.status == PackageStatus.INFO_RECEIVED


async def test_raises_auth_error_on_403(fake_session) -> None:
    fake_session.queue_json("POST", CREATE_OK)
    fake_session.queue_json("GET", {"meta": {"code": 403}}, status=403)
    backend = TrackingMoreBackend(fake_session, api_key="bad-key")

    with pytest.raises(TrackingAuthError):
        await backend.async_track("1234567890")
