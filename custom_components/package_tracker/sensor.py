"""Sensor platform for the Package Tracker integration.

One sensor entity per tracked package, plus a single summary sensor counting
active (non-delivered) packages. Entities are created once at setup time
from whatever the coordinator's first refresh already found - adding,
removing, or archiving a package changes config entry options, which (like
every other option change in this integration) reloads the entry and
therefore re-runs this setup with the current package list, so no dynamic
add-entity machinery is needed here.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PackageTrackerCoordinator, TrackedPackage
from .entity import PackageTrackerEntity
from .models import PackageStatus


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up one sensor per currently-tracked package, plus the summary sensor."""
    coordinator: PackageTrackerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [PackageSummarySensor(coordinator)]
    entities.extend(PackageSensor(coordinator, package_id) for package_id in coordinator.data)
    async_add_entities(entities)


class PackageSensor(PackageTrackerEntity, SensorEntity):
    """Tracks one package's normalized delivery status."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [status.value for status in PackageStatus]

    def __init__(self, coordinator: PackageTrackerCoordinator, package_id: str) -> None:
        super().__init__(coordinator, package_id)
        self._package_id = package_id

    @property
    def _package(self) -> TrackedPackage | None:
        return self.coordinator.data.get(self._package_id)

    @property
    def available(self) -> bool:
        return super().available and self._package is not None

    @property
    def name(self) -> str:
        package = self._package
        return package.name if package else self._package_id

    @property
    def native_value(self) -> str | None:
        package = self._package
        return package.result.status.value if package else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        package = self._package
        if package is None:
            return {}
        result = package.result
        latest = result.latest_event
        return {
            "tracking_number": package.tracking_number,
            "carrier": package.carrier,
            "resolved_carrier": package.resolved_carrier,
            "source": result.source,
            "status_detail": result.status_detail,
            "estimated_delivery": result.estimated_delivery.isoformat() if result.estimated_delivery else None,
            "last_event_description": latest.description if latest else None,
            "last_event_location": latest.location if latest else None,
            "last_event_time": latest.timestamp.isoformat() if latest and latest.timestamp else None,
            "event_count": len(result.events),
        }


class PackageSummarySensor(PackageTrackerEntity, SensorEntity):
    """Counts packages that are not yet delivered."""

    _attr_native_unit_of_measurement = "packages"
    _attr_icon = "mdi:package-variant-closed"

    def __init__(self, coordinator: PackageTrackerCoordinator) -> None:
        super().__init__(coordinator, "summary")

    @property
    def name(self) -> str:
        return "Active packages"

    @property
    def native_value(self) -> int:
        return sum(
            1 for package in self.coordinator.data.values() if package.result.status != PackageStatus.DELIVERED
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            package.name: package.result.status.value
            for package in self.coordinator.data.values()
            if package.result.status != PackageStatus.DELIVERED
        }
