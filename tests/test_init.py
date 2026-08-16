"""Tests for setup/unload and the package_tracker.* services."""

from __future__ import annotations

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.package_tracker.const import (
    CONF_CARRIERS,
    CONF_PACKAGES,
    DOMAIN,
    SERVICE_ADD_PACKAGE,
    SERVICE_REFRESH,
    SERVICE_REMOVE_PACKAGE,
)


def _make_entry(packages: list | None = None) -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, data={}, options={CONF_PACKAGES: packages or [], CONF_CARRIERS: {}})


async def test_setup_entry_registers_services_and_forwards_to_sensor(hass) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, SERVICE_ADD_PACKAGE)
    assert hass.services.has_service(DOMAIN, SERVICE_REMOVE_PACKAGE)
    assert hass.services.has_service(DOMAIN, SERVICE_REFRESH)
    assert hass.states.get("sensor.package_tracker_active_packages") is not None


async def test_add_package_service_adds_and_reloads(hass) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN, SERVICE_ADD_PACKAGE, {"tracking_number": "1Z999AA10123456784"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(entry.options[CONF_PACKAGES]) == 1
    assert entry.options[CONF_PACKAGES][0]["tracking_number"] == "1Z999AA10123456784"


async def test_add_package_service_rejects_duplicate(hass) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN, SERVICE_ADD_PACKAGE, {"tracking_number": "1Z999AA10123456784"}, blocking=True
    )
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, SERVICE_ADD_PACKAGE, {"tracking_number": "1Z999AA10123456784"}, blocking=True
        )


async def test_remove_package_service_removes_existing(hass) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN, SERVICE_ADD_PACKAGE, {"tracking_number": "1Z999AA10123456784"}, blocking=True
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN, SERVICE_REMOVE_PACKAGE, {"tracking_number": "1Z999AA10123456784"}, blocking=True
    )
    await hass.async_block_till_done()

    assert entry.options[CONF_PACKAGES] == []


async def test_remove_package_service_raises_for_unknown_number(hass) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, SERVICE_REMOVE_PACKAGE, {"tracking_number": "does-not-exist"}, blocking=True
        )


async def test_unload_entry_removes_coordinator(hass) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data.get(DOMAIN, {})
