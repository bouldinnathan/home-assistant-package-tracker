"""Package Tracker custom integration for Home Assistant."""

from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    ATTR_CARRIER,
    ATTR_NAME,
    ATTR_TRACKING_NUMBER,
    CARRIER_AUTO,
    DOMAIN,
    NATIVE_CARRIERS,
    PKG_ID,
    PLATFORMS,
    SERVICE_ADD_PACKAGE,
    SERVICE_REFRESH,
    SERVICE_REMOVE_PACKAGE,
)
from .coordinator import PackageTrackerCoordinator
from .packages import build_package, find_package, with_added_package, with_removed_package

_LOGGER = logging.getLogger(__name__)

_PRUNE_INTERVAL = timedelta(hours=6)

_ADD_PACKAGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TRACKING_NUMBER): cv.string,
        vol.Optional(ATTR_CARRIER, default=CARRIER_AUTO): vol.In((CARRIER_AUTO, *NATIVE_CARRIERS)),
        vol.Optional(ATTR_NAME): cv.string,
    }
)
_REMOVE_PACKAGE_SCHEMA = vol.Schema({vol.Required(ATTR_TRACKING_NUMBER): cv.string})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Package Tracker config entry."""
    _LOGGER.debug("Setting up Package Tracker config entry %s", entry.entry_id)

    coordinator = PackageTrackerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    async def _async_prune(_now) -> None:
        await coordinator.async_prune_delivered()

    entry.async_on_unload(async_track_time_interval(hass, _async_prune, _PRUNE_INTERVAL))

    _async_register_services(hass)
    _LOGGER.info("Package Tracker config entry %s set up with %d package(s)", entry.entry_id, len(coordinator.data))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the Package Tracker config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        _LOGGER.info("Package Tracker config entry %s unloaded", entry.entry_id)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry whenever its options change (packages, carrier creds, settings)."""
    _LOGGER.debug("Reloading Package Tracker config entry %s after options update", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


def _get_entry(hass: HomeAssistant) -> ConfigEntry:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError("Package Tracker is not configured")
    return entries[0]


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_ADD_PACKAGE):
        return

    async def _add_package(call: ServiceCall) -> None:
        entry = _get_entry(hass)
        tracking_number = call.data[ATTR_TRACKING_NUMBER]
        if find_package(entry.options, tracking_number=tracking_number) is not None:
            raise HomeAssistantError(f"{tracking_number} is already being tracked")

        package = build_package(
            tracking_number,
            carrier=call.data.get(ATTR_CARRIER, CARRIER_AUTO),
            name=call.data.get(ATTR_NAME),
        )
        _LOGGER.info("Adding package %s (%s) via service call", tracking_number, package[PKG_ID])
        hass.config_entries.async_update_entry(entry, options=with_added_package(dict(entry.options), package))

    async def _remove_package(call: ServiceCall) -> None:
        entry = _get_entry(hass)
        tracking_number = call.data[ATTR_TRACKING_NUMBER]
        package = find_package(entry.options, tracking_number=tracking_number)
        if package is None:
            raise HomeAssistantError(f"No tracked package matches {tracking_number!r}")

        _LOGGER.info("Removing package %s (%s) via service call", tracking_number, package[PKG_ID])
        hass.config_entries.async_update_entry(
            entry, options=with_removed_package(dict(entry.options), package[PKG_ID])
        )

    async def _refresh(_call: ServiceCall) -> None:
        entry = _get_entry(hass)
        coordinator: PackageTrackerCoordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_ADD_PACKAGE, _add_package, schema=_ADD_PACKAGE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_PACKAGE, _remove_package, schema=_REMOVE_PACKAGE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _refresh, schema=vol.Schema({}))
