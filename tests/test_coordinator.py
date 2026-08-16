"""Tests for PackageTrackerCoordinator: backend routing, status-change events, and pruning.

Backend parsing itself is covered in tests/test_backends_*.py; these tests
stub out ``async_track`` entirely so they exercise only the coordinator's own
logic (which backend gets picked, when an event fires, what gets archived).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.package_tracker.backends.aftership import AfterShipBackend
from custom_components.package_tracker.backends.base import TrackingAuthError, TrackingBackendError
from custom_components.package_tracker.backends.seventeentrack import SeventeenTrackBackend
from custom_components.package_tracker.backends.ship24 import Ship24Backend
from custom_components.package_tracker.backends.trackingmore import TrackingMoreBackend
from custom_components.package_tracker.const import (
    BACKEND_AFTERSHIP,
    BACKEND_SEVENTEENTRACK,
    BACKEND_SHIP24,
    BACKEND_TRACKINGMORE,
    CARRIER_DHL,
    CARRIER_UPS,
    CONF_API_KEY,
    CONF_AUTO_ARCHIVE_DAYS,
    CONF_CARRIERS,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_PACKAGES,
    CONF_POLL_INTERVAL,
    DOMAIN,
    EVENT_STATUS_CHANGED,
)
from custom_components.package_tracker.coordinator import (
    PackageTrackerCoordinator,
    _build_fallback_chain,
    _build_native_backends,
)
from custom_components.package_tracker.models import PackageStatus, TrackingResult
from custom_components.package_tracker.packages import build_package


def _make_entry(
    *, carriers: dict | None = None, packages: list | None = None, auto_archive_days: int = 5
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            CONF_CARRIERS: carriers or {},
            CONF_PACKAGES: packages or [],
            CONF_POLL_INTERVAL: 30,
            CONF_AUTO_ARCHIVE_DAYS: auto_archive_days,
        },
    )


def _result(status: PackageStatus, detail: str = "detail") -> TrackingResult:
    return TrackingResult(status=status, status_detail=detail, source="fake", resolved_carrier=CARRIER_UPS)


async def test_uses_native_backend_when_credentials_configured(hass) -> None:
    entry = _make_entry(
        carriers={CARRIER_UPS: {CONF_CLIENT_ID: "id", CONF_CLIENT_SECRET: "secret"}},
        packages=[build_package("1Z999AA10123456784", carrier=CARRIER_UPS)],
    )
    entry.add_to_hass(hass)
    coordinator = PackageTrackerCoordinator(hass, entry)
    ups_backend = AsyncMock()
    ups_backend.async_track.return_value = _result(PackageStatus.IN_TRANSIT)
    coordinator._backends[CARRIER_UPS] = ups_backend

    await coordinator.async_refresh()

    package_id = entry.options[CONF_PACKAGES][0]["id"]
    assert coordinator.data[package_id].result.status == PackageStatus.IN_TRANSIT
    ups_backend.async_track.assert_awaited_once()


async def test_falls_back_to_fallback_chain_when_no_native_credentials(hass) -> None:
    entry = _make_entry(packages=[build_package("1Z999AA10123456784", carrier=CARRIER_UPS)])
    entry.add_to_hass(hass)
    coordinator = PackageTrackerCoordinator(hass, entry)
    fallback = AsyncMock()
    fallback.async_track.return_value = _result(PackageStatus.OUT_FOR_DELIVERY)
    coordinator._fallback_chain = [fallback]

    await coordinator.async_refresh()

    package_id = entry.options[CONF_PACKAGES][0]["id"]
    assert coordinator.data[package_id].result.status == PackageStatus.OUT_FOR_DELIVERY
    fallback.async_track.assert_awaited_once()


async def test_cascades_through_fallback_chain_until_one_succeeds(hass) -> None:
    """Every fallback is assumed likely to fail on its own - the first two here do."""
    entry = _make_entry(packages=[build_package("1Z999AA10123456784", carrier=CARRIER_UPS)])
    entry.add_to_hass(hass)
    coordinator = PackageTrackerCoordinator(hass, entry)

    first = AsyncMock(source="first")
    first.async_track.side_effect = TrackingBackendError("first is down")
    second = AsyncMock(source="second")
    second.async_track.side_effect = TrackingAuthError("second rejected the key")
    third = AsyncMock(source="third")
    third.async_track.return_value = _result(PackageStatus.DELIVERED)
    coordinator._fallback_chain = [first, second, third]

    await coordinator.async_refresh()

    package_id = entry.options[CONF_PACKAGES][0]["id"]
    assert coordinator.data[package_id].result.status == PackageStatus.DELIVERED
    first.async_track.assert_awaited_once()
    second.async_track.assert_awaited_once()
    third.async_track.assert_awaited_once()


async def test_native_failure_cascades_into_fallback_chain(hass) -> None:
    entry = _make_entry(
        carriers={CARRIER_UPS: {CONF_CLIENT_ID: "id", CONF_CLIENT_SECRET: "secret"}},
        packages=[build_package("1Z999AA10123456784", carrier=CARRIER_UPS)],
    )
    entry.add_to_hass(hass)
    coordinator = PackageTrackerCoordinator(hass, entry)
    native = AsyncMock(source="ups")
    native.async_track.side_effect = TrackingBackendError("UPS API is down")
    fallback = AsyncMock(source="fallback")
    fallback.async_track.return_value = _result(PackageStatus.IN_TRANSIT)
    coordinator._backends[CARRIER_UPS] = native
    coordinator._fallback_chain = [fallback]

    await coordinator.async_refresh()

    package_id = entry.options[CONF_PACKAGES][0]["id"]
    assert coordinator.data[package_id].result.status == PackageStatus.IN_TRANSIT
    native.async_track.assert_awaited_once()
    fallback.async_track.assert_awaited_once()


async def test_carries_forward_previous_result_when_every_candidate_fails(hass) -> None:
    entry = _make_entry(packages=[build_package("1Z999AA10123456784", carrier=CARRIER_UPS)])
    entry.add_to_hass(hass)
    coordinator = PackageTrackerCoordinator(hass, entry)

    working = AsyncMock(source="working")
    working.async_track.return_value = _result(PackageStatus.IN_TRANSIT)
    coordinator._fallback_chain = [working]
    await coordinator.async_refresh()

    always_fails_a = AsyncMock(source="a")
    always_fails_a.async_track.side_effect = TrackingBackendError("down")
    always_fails_b = AsyncMock(source="b")
    always_fails_b.async_track.side_effect = Exception("boom")
    coordinator._fallback_chain = [always_fails_a, always_fails_b]
    await coordinator.async_refresh()

    package_id = entry.options[CONF_PACKAGES][0]["id"]
    assert coordinator.data[package_id].result.status == PackageStatus.IN_TRANSIT
    always_fails_a.async_track.assert_awaited_once()
    always_fails_b.async_track.assert_awaited_once()


async def test_needs_configuration_when_no_backend_available(hass) -> None:
    entry = _make_entry(packages=[build_package("1Z999AA10123456784", carrier=CARRIER_UPS)])
    entry.add_to_hass(hass)
    coordinator = PackageTrackerCoordinator(hass, entry)

    await coordinator.async_refresh()

    package_id = entry.options[CONF_PACKAGES][0]["id"]
    assert coordinator.data[package_id].result.status == PackageStatus.NEEDS_CONFIGURATION


async def test_fires_event_only_when_status_actually_changes(hass) -> None:
    entry = _make_entry(packages=[build_package("1Z999AA10123456784", carrier=CARRIER_UPS)])
    entry.add_to_hass(hass)
    coordinator = PackageTrackerCoordinator(hass, entry)
    backend = AsyncMock()
    backend.async_track.side_effect = [
        _result(PackageStatus.IN_TRANSIT),
        _result(PackageStatus.IN_TRANSIT),
        _result(PackageStatus.DELIVERED),
    ]
    coordinator._backends[CARRIER_UPS] = backend

    events = []
    hass.bus.async_listen(EVENT_STATUS_CHANGED, lambda event: events.append(event.data))

    await coordinator.async_refresh()  # first observation: no previous status, no event
    await coordinator.async_refresh()  # unchanged: no event
    await coordinator.async_refresh()  # changed: fires
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0]["previous_status"] == "in_transit"
    assert events[0]["status"] == "delivered"


async def test_carries_forward_previous_result_on_backend_error(hass) -> None:
    entry = _make_entry(packages=[build_package("1Z999AA10123456784", carrier=CARRIER_UPS)])
    entry.add_to_hass(hass)
    coordinator = PackageTrackerCoordinator(hass, entry)
    backend = AsyncMock()
    backend.async_track.side_effect = [_result(PackageStatus.IN_TRANSIT), Exception("boom")]
    coordinator._backends[CARRIER_UPS] = backend

    await coordinator.async_refresh()
    await coordinator.async_refresh()

    package_id = entry.options[CONF_PACKAGES][0]["id"]
    assert coordinator.data[package_id].result.status == PackageStatus.IN_TRANSIT


async def test_prune_delivered_archives_packages_past_grace_period(hass) -> None:
    entry = _make_entry(packages=[build_package("1Z999AA10123456784", carrier=CARRIER_UPS)], auto_archive_days=1)
    entry.add_to_hass(hass)
    coordinator = PackageTrackerCoordinator(hass, entry)
    package_id = entry.options[CONF_PACKAGES][0]["id"]
    coordinator._delivered_since[package_id] = dt_util.utcnow() - timedelta(days=5)

    archived = await coordinator.async_prune_delivered()

    assert archived == [package_id]
    assert entry.options[CONF_PACKAGES][0]["archived"] is True


async def test_prune_delivered_is_a_noop_when_auto_archive_disabled(hass) -> None:
    entry = _make_entry(packages=[build_package("1Z999AA10123456784", carrier=CARRIER_UPS)], auto_archive_days=0)
    entry.add_to_hass(hass)
    coordinator = PackageTrackerCoordinator(hass, entry)
    package_id = entry.options[CONF_PACKAGES][0]["id"]
    coordinator._delivered_since[package_id] = dt_util.utcnow() - timedelta(days=999)

    archived = await coordinator.async_prune_delivered()

    assert archived == []
    assert entry.options[CONF_PACKAGES][0]["archived"] is False


async def test_build_native_backends_requires_complete_credentials(hass) -> None:
    options = {CONF_CARRIERS: {CARRIER_UPS: {CONF_CLIENT_ID: "id-only"}}}
    backends = _build_native_backends(hass, options)
    assert CARRIER_UPS not in backends


async def test_build_native_backends_includes_carrier_with_complete_credentials(hass) -> None:
    options = {CONF_CARRIERS: {CARRIER_UPS: {CONF_CLIENT_ID: "id", CONF_CLIENT_SECRET: "secret"}}}
    backends = _build_native_backends(hass, options)
    assert CARRIER_UPS in backends
    assert CARRIER_DHL not in backends


async def test_build_fallback_chain_empty_without_any_api_key(hass) -> None:
    assert _build_fallback_chain(hass, {CONF_CARRIERS: {}}) == []


async def test_build_fallback_chain_includes_only_configured_aggregators_in_fixed_order(hass) -> None:
    options = {
        CONF_CARRIERS: {
            BACKEND_SHIP24: {CONF_API_KEY: "ship24-key"},
            BACKEND_SEVENTEENTRACK: {CONF_API_KEY: "17track-key"},
        }
    }

    chain = _build_fallback_chain(hass, options)

    assert [type(backend) for backend in chain] == [SeventeenTrackBackend, Ship24Backend]


async def test_build_fallback_chain_includes_all_four_when_fully_configured(hass) -> None:
    options = {
        CONF_CARRIERS: {
            BACKEND_SEVENTEENTRACK: {CONF_API_KEY: "a"},
            BACKEND_AFTERSHIP: {CONF_API_KEY: "b"},
            BACKEND_TRACKINGMORE: {CONF_API_KEY: "c"},
            BACKEND_SHIP24: {CONF_API_KEY: "d"},
        }
    }

    chain = _build_fallback_chain(hass, options)

    assert [type(backend) for backend in chain] == [
        SeventeenTrackBackend,
        AfterShipBackend,
        TrackingMoreBackend,
        Ship24Backend,
    ]
