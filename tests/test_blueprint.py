"""Run the shipped notification blueprint through Home Assistant automation."""

from pathlib import Path

from homeassistant.setup import async_setup_component
from homeassistant.util import yaml as yaml_util

from custom_components.package_tracker.const import EVENT_STATUS_CHANGED


async def test_blueprint_sends_selected_status_with_package_details(hass, tmp_path) -> None:
    # Automation installs example blueprints; keep those writes out of the repo.
    hass.config.config_dir = str(tmp_path)
    path = Path(__file__).resolve().parents[1] / "blueprints/automation/package_tracker/notify_on_status_change.yaml"
    blueprint = await hass.async_add_executor_job(yaml_util.load_yaml, str(path))
    inputs = {"notify_action": "notify.test_phone", "statuses": ["delivered"]}
    config = yaml_util.substitute(blueprint, inputs)
    config.pop("blueprint")
    config["alias"] = "Package test"
    received = []

    async def notify(call):
        received.append(call.data)

    hass.services.async_register("notify", "test_phone", notify)
    assert await async_setup_component(hass, "automation", {"automation": [config]})
    await hass.async_start()
    await hass.async_block_till_done()
    assert hass.states.get("automation.package_test") is not None

    data = {"carrier": "ups", "name": "Gift", "status_detail": "At your door"}
    hass.bus.async_fire(EVENT_STATUS_CHANGED, {**data, "status": "in_transit"})
    await hass.async_block_till_done()
    assert received == []
    hass.bus.async_fire(EVENT_STATUS_CHANGED, {**data, "status": "delivered"})
    await hass.async_block_till_done()
    assert received == [{"title": "UPS - Delivered", "message": "Gift: At your door"}]
