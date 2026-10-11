"""Tests for the Package Tracker config and options flows, driven through the real FlowManager."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.package_tracker.const import (
    BACKEND_AFTERSHIP,
    CARRIER_UPS,
    CONF_API_KEY,
    CONF_AUTO_ARCHIVE_DAYS,
    CONF_CARRIERS,
    CONF_CLIENT_ID,
    CONF_PACKAGES,
    CONF_POLL_INTERVAL,
    DOMAIN,
    PKG_ARCHIVED,
)
from custom_components.package_tracker.packages import build_package


async def test_user_step_creates_entry_with_default_options(hass) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_PACKAGES] == []
    assert result["options"][CONF_CARRIERS] == {}


async def test_user_step_aborts_when_already_configured(hass) -> None:
    MockConfigEntry(domain=DOMAIN, data={}, options={}).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def _init_options(hass, entry: MockConfigEntry):
    entry.add_to_hass(hass)
    return await hass.config_entries.options.async_init(entry.entry_id)


async def test_options_menu_offers_all_steps(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_PACKAGES: [], CONF_CARRIERS: {}})
    result = await _init_options(hass, entry)

    assert result["type"] == FlowResultType.MENU
    assert set(result["menu_options"]) == {"add_package", "manage_packages", "carriers", "settings"}


async def test_add_package_creates_entry_with_new_package(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_PACKAGES: [], CONF_CARRIERS: {}})
    result = await _init_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_package"}
    )
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_number": "1Z999AA10123456784", "carrier": "auto", "name": ""}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert len(result["data"][CONF_PACKAGES]) == 1
    assert result["data"][CONF_PACKAGES][0]["tracking_number"] == "1Z999AA10123456784"


async def test_add_package_rejects_empty_tracking_number(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_PACKAGES: [], CONF_CARRIERS: {}})
    result = await _init_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_package"}
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_number": "   ", "carrier": "auto", "name": ""}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["tracking_number"] == "required"


async def test_add_package_rejects_duplicate_tracking_number(hass) -> None:
    existing = build_package("1Z999AA10123456784", carrier=CARRIER_UPS)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_PACKAGES: [existing], CONF_CARRIERS: {}})
    result = await _init_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_package"}
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_number": "1z999aa10123456784", "carrier": "auto", "name": ""}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["tracking_number"] == "already_tracked"


async def test_manage_packages_removes_selected_package(hass) -> None:
    existing = build_package("1Z999AA10123456784", carrier=CARRIER_UPS)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_PACKAGES: [existing], CONF_CARRIERS: {}})
    result = await _init_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "manage_packages"}
    )
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"remove_ids": [existing["id"]]}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PACKAGES] == []


async def test_manage_packages_includes_archived_packages(hass) -> None:
    package = {**build_package("1Z999AA10123456784"), PKG_ARCHIVED: True}
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_PACKAGES: [package]})
    result = await _init_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "manage_packages"}
    )
    assert result["data_schema"]({"remove_ids": [package["id"]]})["remove_ids"] == [package["id"]]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"remove_ids": [package["id"]]}
    )
    assert result["data"][CONF_PACKAGES] == []


async def test_carriers_step_persists_credentials(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_PACKAGES: [], CONF_CARRIERS: {}})
    result = await _init_options(hass, entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "carriers"})

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"ups_client_id": "abc", "ups_client_secret": "xyz", "aftership_api_key": "as-key"},
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CARRIERS][CARRIER_UPS][CONF_CLIENT_ID] == "abc"
    assert result["data"][CONF_CARRIERS][BACKEND_AFTERSHIP][CONF_API_KEY] == "as-key"


async def test_settings_step_persists_poll_interval_and_archive_days(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_PACKAGES: [], CONF_CARRIERS: {}})
    result = await _init_options(hass, entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: 60, CONF_AUTO_ARCHIVE_DAYS: 10}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_POLL_INTERVAL] == 60
    assert result["data"][CONF_AUTO_ARCHIVE_DAYS] == 10
