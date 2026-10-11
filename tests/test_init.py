"""Tests for setup/unload and the package_tracker.* services."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.package_tracker.const import (
    CONF_CARRIERS,
    CONF_PACKAGES,
    DOMAIN,
    PKG_ARCHIVED,
    SERVICE_ADD_PACKAGE,
    SERVICE_REFRESH,
    SERVICE_REMOVE_PACKAGE,
)
from custom_components.package_tracker.packages import build_package


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


@pytest.mark.parametrize("number", ["", " \t\n "])
async def test_add_package_service_rejects_blank_numbers(hass, number) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    with pytest.raises(HomeAssistantError, match="tracking number"):
        await hass.services.async_call(
            DOMAIN, SERVICE_ADD_PACKAGE, {"tracking_number": number}, blocking=True
        )
    assert entry.options[CONF_PACKAGES] == []


@pytest.mark.parametrize("archive", [False, True])
async def test_removed_or_archived_package_is_removed_from_registry(hass, archive) -> None:
    package = build_package("1Z999AA10123456784", name="Gift")
    entry = _make_entry([package])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{package['id']}")
    assert entity_id is not None

    packages = [{**package, PKG_ARCHIVED: True}] if archive else []
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_PACKAGES: packages})
    await hass.async_block_till_done()

    assert registry.async_get(entity_id) is None
    assert hass.states.get(entity_id) is None
    assert hass.states.get("sensor.package_tracker_active_packages") is not None


async def test_refresh_when_unloaded_reports_friendly_error(hass) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(HomeAssistantError, match="not loaded"):
        await hass.services.async_call(DOMAIN, SERVICE_REFRESH, {}, blocking=True)


async def test_failed_platform_setup_rolls_back_and_can_retry(hass) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    with patch.object(hass.config_entries, "async_forward_entry_setups", side_effect=RuntimeError("Setup failed")):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.package_tracker_active_packages") is not None
