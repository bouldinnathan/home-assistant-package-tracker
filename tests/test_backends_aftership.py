"""Tests for the AfterShip aggregator fallback backend."""

from __future__ import annotations

import pytest

from custom_components.package_tracker.backends.aftership import AfterShipBackend
from custom_components.package_tracker.backends.base import TrackingAuthError
from custom_components.package_tracker.const import CARRIER_UPS
from custom_components.package_tracker.models import PackageStatus

CREATE_OK = {"meta": {"code": 201}, "data": {"tracking": {"tracking_number": "1Z999AA10123456784"}}}
LIST_WITH_RESULT = {
    "meta": {"code": 200},
    "data": {
        "trackings": [
            {
                "tracking_number": "1Z999AA10123456784",
                "tag": "OutForDelivery",
                "slug": "ups",
                "expected_delivery": "2026-08-05",
                "checkpoints": [
                    {
                        "checkpoint_time": "2026-08-05T08:00:00Z",
                        "message": "Out for delivery",
                        "city": "Austin",
                        "state": "TX",
                        "country_name": "United States",
                    },
                ],
            }
        ]
    },
}
LIST_EMPTY = {"meta": {"code": 200}, "data": {"trackings": []}}


async def test_creates_then_tracks_a_new_number(fake_session) -> None:
    fake_session.queue_json("POST", CREATE_OK, status=201)
    fake_session.queue_json("GET", LIST_WITH_RESULT)
    backend = AfterShipBackend(fake_session, api_key="key")

    result = await backend.async_track("1Z999AA10123456784")

    assert result.status == PackageStatus.OUT_FOR_DELIVERY
    assert result.resolved_carrier == CARRIER_UPS
    assert result.source == "aftership"
    assert len(result.events) == 1
    assert result.events[0].location == "Austin, TX, United States"
    assert result.estimated_delivery is not None
    assert len(fake_session.calls) == 2


async def test_does_not_recreate_an_already_seen_number(fake_session) -> None:
    fake_session.queue_json("POST", CREATE_OK, status=201)
    fake_session.queue_json("GET", LIST_WITH_RESULT)
    fake_session.queue_json("GET", LIST_WITH_RESULT)
    backend = AfterShipBackend(fake_session, api_key="key")

    await backend.async_track("1Z999AA10123456784")
    await backend.async_track("1Z999AA10123456784")

    assert len(fake_session.calls) == 3  # one create + two list calls, no second create


async def test_not_yet_resolved_number_reports_info_received(fake_session) -> None:
    fake_session.queue_json("POST", CREATE_OK, status=201)
    fake_session.queue_json("GET", LIST_EMPTY)
    backend = AfterShipBackend(fake_session, api_key="key")

    result = await backend.async_track("1Z999AA10123456784")

    assert result.status == PackageStatus.INFO_RECEIVED


async def test_raises_auth_error_on_401(fake_session) -> None:
    fake_session.queue_json("POST", CREATE_OK, status=201)
    fake_session.queue_json("GET", {"meta": {"code": 401}}, status=401)
    backend = AfterShipBackend(fake_session, api_key="bad-key")

    with pytest.raises(TrackingAuthError):
        await backend.async_track("1Z999AA10123456784")
