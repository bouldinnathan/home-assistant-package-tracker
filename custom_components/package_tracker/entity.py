"""Base entity for the Package Tracker integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, NAME
from .coordinator import PackageTrackerCoordinator


class PackageTrackerEntity(CoordinatorEntity[PackageTrackerCoordinator]):
    """Base entity bound to the single shared Package Tracker hub device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PackageTrackerCoordinator, unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{unique_suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        """Every package sensor lives under one hub device - there's no per-package hardware."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
        )
