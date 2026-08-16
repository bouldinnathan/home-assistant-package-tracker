"""Tests for the PackageSensor and PackageSummarySensor entity classes."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.package_tracker.const import CARRIER_UPS, CONF_CARRIERS, CONF_PACKAGES, DOMAIN
from custom_components.package_tracker.coordinator import PackageTrackerCoordinator
from custom_components.package_tracker.models import PackageStatus, TrackingResult
from custom_components.package_tracker.packages import build_package
from custom_components.package_tracker.sensor import PackageSensor, PackageSummarySensor


async def test_package_sensor_reflects_latest_result(hass) -> None:
    package = build_package("1Z999AA10123456784", carrier=CARRIER_UPS, name="Gift")
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_PACKAGES: [package], CONF_CARRIERS: {}})
    entry.add_to_hass(hass)
    coordinator = PackageTrackerCoordinator(hass, entry)
    backend = AsyncMock()
    backend.async_track.return_value = TrackingResult(
        status=PackageStatus.OUT_FOR_DELIVERY,
        status_detail="Almost there",
        source="ups",
        resolved_carrier=CARRIER_UPS,
    )
    coordinator._backends[CARRIER_UPS] = backend
    await coordinator.async_refresh()

    sensor = PackageSensor(coordinator, package["id"])

    assert sensor.name == "Gift"
    assert sensor.native_value == "out_for_delivery"
    assert sensor.extra_state_attributes["tracking_number"] == "1Z999AA10123456784"
    assert sensor.extra_state_attributes["status_detail"] == "Almost there"


async def test_package_summary_sensor_counts_undelivered_packages(hass) -> None:
    delivered = build_package("1Z999AA10123456784", carrier=CARRIER_UPS)
    unconfigured = build_package("123456789012")  # auto-detects to fedex, no backend configured
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, options={CONF_PACKAGES: [delivered, unconfigured], CONF_CARRIERS: {}}
    )
    entry.add_to_hass(hass)
    coordinator = PackageTrackerCoordinator(hass, entry)
    backend = AsyncMock()
    backend.async_track.return_value = TrackingResult(
        status=PackageStatus.DELIVERED, status_detail="", source="ups", resolved_carrier=CARRIER_UPS
    )
    coordinator._backends[CARRIER_UPS] = backend
    await coordinator.async_refresh()

    summary = PackageSummarySensor(coordinator)

    # `unconfigured` reports NEEDS_CONFIGURATION, not DELIVERED, so it still
    # counts toward the active total even though no real tracking happened.
    assert summary.native_value == 1
