"""Tests for the 17track.net aggregator fallback backend."""

from __future__ import annotations

import pytest

from custom_components.package_tracker.backends.base import TrackingAuthError
from custom_components.package_tracker.backends.seventeentrack import SeventeenTrackBackend
from custom_components.package_tracker.const import CARRIER_UPS
from custom_components.package_tracker.models import PackageStatus

REGISTER_OK = {"code": 0, "data": {"accepted": [{"number": "1Z999AA10123456784"}], "rejected": []}}
TRACK_BODY_ACCEPTED = {
    "code": 0,
    "data": {
        "accepted": [
            {
                "number": "1Z999AA10123456784",
                "carrier_name": "UPS",
                "track_info": {
                    "latest_status": {"status": "InTransit"},
                    "latest_event": {"description": "Departed facility"},
                    "time_metrics": {"estimated_delivery_date": {"from": "2026-08-05T00:00:00Z", "to": "2026-08-06T00:00:00Z"}},
                    "tracking": {
                        "providers": [
                            {
                                "events": [
                                    {"time_iso": "2026-08-04T20:00:00Z", "description": "Departed facility", "location": "Dallas, TX"},
                                ]
                            }
                        ]
                    },
                },
            }
        ],
        "rejected": [],
    },
}
TRACK_BODY_NOT_YET_ACCEPTED = {"code": 0, "data": {"accepted": [], "rejected": []}}


async def test_registers_then_tracks_a_new_number(fake_session) -> None:
    fake_session.queue_json("POST", REGISTER_OK)
    fake_session.queue_json("POST", TRACK_BODY_ACCEPTED)
    backend = SeventeenTrackBackend(fake_session, api_key="key")

    result = await backend.async_track("1Z999AA10123456784")

    assert result.status == PackageStatus.IN_TRANSIT
    assert result.resolved_carrier == CARRIER_UPS
    assert result.source == "seventeentrack"
    assert len(result.events) == 1
    assert result.estimated_delivery is not None
    assert len(fake_session.calls) == 2


async def test_does_not_re_register_an_already_registered_number(fake_session) -> None:
    fake_session.queue_json("POST", REGISTER_OK)
    fake_session.queue_json("POST", TRACK_BODY_ACCEPTED)
    fake_session.queue_json("POST", TRACK_BODY_ACCEPTED)
    backend = SeventeenTrackBackend(fake_session, api_key="key")

    await backend.async_track("1Z999AA10123456784")
    await backend.async_track("1Z999AA10123456784")

    assert len(fake_session.calls) == 3  # one register + two gettrackinfo, no second register


async def test_not_yet_processed_number_reports_info_received(fake_session) -> None:
    fake_session.queue_json("POST", REGISTER_OK)
    fake_session.queue_json("POST", TRACK_BODY_NOT_YET_ACCEPTED)
    backend = SeventeenTrackBackend(fake_session, api_key="key")

    result = await backend.async_track("1Z999AA10123456784")

    assert result.status == PackageStatus.INFO_RECEIVED


async def test_raises_auth_error_on_401(fake_session) -> None:
    fake_session.queue_json("POST", REGISTER_OK)
    fake_session.queue_json("POST", {"code": 401}, status=401)
    backend = SeventeenTrackBackend(fake_session, api_key="bad-key")

    with pytest.raises(TrackingAuthError):
        await backend.async_track("1Z999AA10123456784")
