"""Config and options flow for the Package Tracker integration.

Setup itself needs no input - there's exactly one config entry
(``single_config_entry`` in the manifest), and it starts with no carrier
credentials and no packages. Everything a user actually wants to do -
"paste a tracking number," "add a carrier API key," "stop tracking this
one," "change the poll interval" - lives in the options flow, reachable any
time from Settings -> Devices & Services -> Package Tracker -> Configure.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    BACKEND_AFTERSHIP,
    BACKEND_SEVENTEENTRACK,
    BACKEND_SHIP24,
    BACKEND_TRACKINGMORE,
    CARRIER_AUTO,
    CARRIER_DHL,
    CARRIER_FEDEX,
    CARRIER_UPS,
    CARRIER_USPS,
    CONF_API_KEY,
    CONF_AUTO_ARCHIVE_DAYS,
    CONF_CARRIERS,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_PACKAGES,
    CONF_POLL_INTERVAL,
    DEFAULT_AUTO_ARCHIVE_DAYS,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_AUTO_ARCHIVE_DAYS,
    MAX_POLL_INTERVAL,
    MIN_AUTO_ARCHIVE_DAYS,
    MIN_POLL_INTERVAL,
    NAME,
    PKG_ARCHIVED,
    PKG_CARRIER,
    PKG_ID,
    PKG_NAME,
    PKG_TRACKING_NUMBER,
)
from .packages import build_package, find_package, with_added_package, with_removed_package

_CARRIER_CHOICES = {
    CARRIER_AUTO: "Auto-detect",
    CARRIER_UPS: "UPS",
    CARRIER_FEDEX: "FedEx",
    CARRIER_DHL: "DHL",
    CARRIER_USPS: "USPS",
}

_DEFAULT_OPTIONS: dict[str, Any] = {
    CONF_CARRIERS: {},
    CONF_PACKAGES: [],
    CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL,
    CONF_AUTO_ARCHIVE_DAYS: DEFAULT_AUTO_ARCHIVE_DAYS,
}


class PackageTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """One-step setup; all real configuration happens in the options flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Create the single Package Tracker entry."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={}, options=dict(_DEFAULT_OPTIONS))
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> PackageTrackerOptionsFlow:
        """Return the options flow for this entry."""
        return PackageTrackerOptionsFlow()


class PackageTrackerOptionsFlow(config_entries.OptionsFlow):
    """Menu-driven options: add/manage packages, carrier credentials, and polling settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_package", "manage_packages", "carriers", "settings"],
        )

    async def async_step_add_package(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        options = dict(self.config_entry.options)

        if user_input is not None:
            tracking_number = user_input[PKG_TRACKING_NUMBER].strip()
            if not tracking_number:
                errors[PKG_TRACKING_NUMBER] = "required"
            elif find_package(options, tracking_number=tracking_number) is not None:
                errors[PKG_TRACKING_NUMBER] = "already_tracked"

            if not errors:
                package = build_package(
                    tracking_number,
                    carrier=user_input.get(PKG_CARRIER, CARRIER_AUTO),
                    name=user_input.get(PKG_NAME, "").strip() or None,
                )
                return self.async_create_entry(title="", data=with_added_package(options, package))

        schema = vol.Schema(
            {
                vol.Required(PKG_TRACKING_NUMBER): str,
                vol.Optional(PKG_CARRIER, default=CARRIER_AUTO): vol.In(_CARRIER_CHOICES),
                vol.Optional(PKG_NAME, default=""): str,
            }
        )
        return self.async_show_form(step_id="add_package", data_schema=schema, errors=errors)

    async def async_step_manage_packages(self, user_input: dict[str, Any] | None = None):
        options = dict(self.config_entry.options)
        packages = options.get(CONF_PACKAGES, [])

        if user_input is not None:
            remove_ids = set(user_input.get("remove_ids", []))
            for package_id in remove_ids:
                options = with_removed_package(options, package_id)
            return self.async_create_entry(title="", data=options)

        if not packages:
            return self.async_show_form(step_id="manage_packages", data_schema=vol.Schema({}))

        choices = {
            pkg[PKG_ID]: f"{pkg.get(PKG_NAME) or pkg[PKG_TRACKING_NUMBER]} ({pkg[PKG_TRACKING_NUMBER]}, {_CARRIER_CHOICES.get(pkg.get(PKG_CARRIER, CARRIER_AUTO), pkg.get(PKG_CARRIER))}){' [archived]' if pkg.get(PKG_ARCHIVED) else ''}"
            for pkg in packages
        }
        schema = vol.Schema({vol.Optional("remove_ids", default=[]): cv.multi_select(choices)})
        return self.async_show_form(step_id="manage_packages", data_schema=schema)

    async def async_step_carriers(self, user_input: dict[str, Any] | None = None):
        options = dict(self.config_entry.options)
        carriers = dict(options.get(CONF_CARRIERS, {}))

        if user_input is not None:
            carriers[CARRIER_UPS] = {
                CONF_CLIENT_ID: user_input.get("ups_client_id", "").strip(),
                CONF_CLIENT_SECRET: user_input.get("ups_client_secret", "").strip(),
            }
            carriers[CARRIER_FEDEX] = {
                CONF_CLIENT_ID: user_input.get("fedex_client_id", "").strip(),
                CONF_CLIENT_SECRET: user_input.get("fedex_client_secret", "").strip(),
            }
            carriers[CARRIER_DHL] = {CONF_API_KEY: user_input.get("dhl_api_key", "").strip()}
            carriers[CARRIER_USPS] = {
                CONF_CLIENT_ID: user_input.get("usps_client_id", "").strip(),
                CONF_CLIENT_SECRET: user_input.get("usps_client_secret", "").strip(),
            }
            carriers[BACKEND_SEVENTEENTRACK] = {CONF_API_KEY: user_input.get("seventeentrack_api_key", "").strip()}
            carriers[BACKEND_AFTERSHIP] = {CONF_API_KEY: user_input.get("aftership_api_key", "").strip()}
            carriers[BACKEND_TRACKINGMORE] = {CONF_API_KEY: user_input.get("trackingmore_api_key", "").strip()}
            carriers[BACKEND_SHIP24] = {CONF_API_KEY: user_input.get("ship24_api_key", "").strip()}
            options[CONF_CARRIERS] = carriers
            return self.async_create_entry(title="", data=options)

        ups = carriers.get(CARRIER_UPS, {})
        fedex = carriers.get(CARRIER_FEDEX, {})
        dhl = carriers.get(CARRIER_DHL, {})
        usps = carriers.get(CARRIER_USPS, {})
        seventeentrack = carriers.get(BACKEND_SEVENTEENTRACK, {})
        aftership = carriers.get(BACKEND_AFTERSHIP, {})
        trackingmore = carriers.get(BACKEND_TRACKINGMORE, {})
        ship24 = carriers.get(BACKEND_SHIP24, {})
        schema = vol.Schema(
            {
                vol.Optional("ups_client_id", default=ups.get(CONF_CLIENT_ID, "")): str,
                vol.Optional("ups_client_secret", default=ups.get(CONF_CLIENT_SECRET, "")): str,
                vol.Optional("fedex_client_id", default=fedex.get(CONF_CLIENT_ID, "")): str,
                vol.Optional("fedex_client_secret", default=fedex.get(CONF_CLIENT_SECRET, "")): str,
                vol.Optional("dhl_api_key", default=dhl.get(CONF_API_KEY, "")): str,
                vol.Optional("usps_client_id", default=usps.get(CONF_CLIENT_ID, "")): str,
                vol.Optional("usps_client_secret", default=usps.get(CONF_CLIENT_SECRET, "")): str,
                vol.Optional("seventeentrack_api_key", default=seventeentrack.get(CONF_API_KEY, "")): str,
                vol.Optional("aftership_api_key", default=aftership.get(CONF_API_KEY, "")): str,
                vol.Optional("trackingmore_api_key", default=trackingmore.get(CONF_API_KEY, "")): str,
                vol.Optional("ship24_api_key", default=ship24.get(CONF_API_KEY, "")): str,
            }
        )
        return self.async_show_form(step_id="carriers", data_schema=schema)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None):
        options = dict(self.config_entry.options)

        if user_input is not None:
            options[CONF_POLL_INTERVAL] = user_input[CONF_POLL_INTERVAL]
            options[CONF_AUTO_ARCHIVE_DAYS] = user_input[CONF_AUTO_ARCHIVE_DAYS]
            return self.async_create_entry(title="", data=options)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_POLL_INTERVAL, default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
                ): vol.All(int, vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL)),
                vol.Optional(
                    CONF_AUTO_ARCHIVE_DAYS, default=options.get(CONF_AUTO_ARCHIVE_DAYS, DEFAULT_AUTO_ARCHIVE_DAYS)
                ): vol.All(int, vol.Range(min=MIN_AUTO_ARCHIVE_DAYS, max=MAX_AUTO_ARCHIVE_DAYS)),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)
