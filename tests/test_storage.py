"""Check cache recovery and deletion through the Home Assistant lifecycle."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.package_tracker.const import CONF_PACKAGES, DOMAIN
from custom_components.package_tracker.packages import build_package
from custom_components.package_tracker.storage import TrackingStore


async def test_invalid_cached_result_does_not_prevent_setup(hass) -> None:
    package = build_package("1Z999AA10123456784")
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_PACKAGES: [package]})
    entry.add_to_hass(hass)
    store = TrackingStore(hass, entry.entry_id)
    await store.async_save({package["id"]: {"result": {"status": "invalid"}}})
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert hass.data[DOMAIN][entry.entry_id].data[package["id"]].result.status == "needs_configuration"


async def test_removing_integration_deletes_cache(hass, hass_storage) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_PACKAGES: []})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    key = f"{DOMAIN}.{entry.entry_id}"
    assert key in hass_storage
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage
