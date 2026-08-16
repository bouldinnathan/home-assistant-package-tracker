"""Diagnostics support for Package Tracker."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DIAGNOSTIC_REDACT, DOMAIN, VERSION
from .coordinator import PackageTrackerCoordinator


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return a redacted diagnostics snapshot for the Package Tracker config entry."""
    coordinator: PackageTrackerCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    packages: list[dict[str, Any]] = []
    if coordinator is not None:
        for tracked in coordinator.data.values():
            packages.append(
                {
                    "tracking_number": tracked.tracking_number,
                    "carrier": tracked.carrier,
                    "resolved_carrier": tracked.resolved_carrier,
                    "status": tracked.result.status.value,
                    "source": tracked.result.source,
                    "event_count": len(tracked.result.events),
                }
            )

    diagnostics: dict[str, Any] = {
        "integration_version": VERSION,
        "entry_options": dict(entry.options),
        "coordinator": {
            "loaded": coordinator is not None,
            "last_update_success": coordinator.last_update_success if coordinator else None,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator is not None and coordinator.update_interval
                else None
            ),
        },
        "packages": packages,
    }
    return async_redact_data(diagnostics, DIAGNOSTIC_REDACT)
