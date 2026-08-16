"""Tests for diagnostics credential redaction."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.package_tracker.const import (
    CARRIER_UPS,
    CONF_CARRIERS,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_PACKAGES,
    DOMAIN,
)
from custom_components.package_tracker.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redacts_carrier_credentials(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            CONF_PACKAGES: [],
            CONF_CARRIERS: {CARRIER_UPS: {CONF_CLIENT_ID: "abc", CONF_CLIENT_SECRET: "super-secret"}},
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    carrier_options = diagnostics["entry_options"][CONF_CARRIERS][CARRIER_UPS]
    assert carrier_options[CONF_CLIENT_ID] == "**REDACTED**"
    assert carrier_options[CONF_CLIENT_SECRET] == "**REDACTED**"
    assert diagnostics["coordinator"]["loaded"] is True
