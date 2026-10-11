"""Constants for the Package Tracker integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "package_tracker"
NAME: Final = "Package Tracker"
VERSION: Final = "0.1.1"
MANUFACTURER: Final = "Package Tracker"

PLATFORMS: Final = ["sensor"]

# Carrier identifiers used throughout options, entities, and backend routing.
CARRIER_UPS: Final = "ups"
CARRIER_FEDEX: Final = "fedex"
CARRIER_DHL: Final = "dhl"
CARRIER_USPS: Final = "usps"
CARRIER_AUTO: Final = "auto"
CARRIER_UNKNOWN: Final = "unknown"

NATIVE_CARRIERS: Final = (CARRIER_UPS, CARRIER_FEDEX, CARRIER_DHL, CARRIER_USPS)
CARRIER_NAMES: Final = {
    CARRIER_UPS: "UPS",
    CARRIER_FEDEX: "FedEx",
    CARRIER_DHL: "DHL",
    CARRIER_USPS: "USPS",
    CARRIER_AUTO: "Auto-detect",
    CARRIER_UNKNOWN: "Unknown",
}

BACKEND_SEVENTEENTRACK: Final = "seventeentrack"
BACKEND_AFTERSHIP: Final = "aftership"
BACKEND_TRACKINGMORE: Final = "trackingmore"
BACKEND_SHIP24: Final = "ship24"

# Fallback aggregators are tried in this fixed order for any package whose
# resolved carrier has no native credentials configured (or whose native
# backend just failed) - each is assumed unreliable on its own, so the
# coordinator cascades through all of them before giving up. See
# coordinator.py's _build_fallback_chain().
FALLBACK_BACKENDS: Final = (BACKEND_SEVENTEENTRACK, BACKEND_AFTERSHIP, BACKEND_TRACKINGMORE, BACKEND_SHIP24)
FALLBACK_BACKEND_NAMES: Final = {
    BACKEND_SEVENTEENTRACK: "17track",
    BACKEND_AFTERSHIP: "AfterShip",
    BACKEND_TRACKINGMORE: "TrackingMore",
    BACKEND_SHIP24: "Ship24",
}

# Options dict layout: entry.options = {
#   CONF_CARRIERS: {carrier: {credential_key: value, ...}, ...},
#   CONF_PACKAGES: [{...package...}, ...],
#   CONF_POLL_INTERVAL: int,
#   CONF_AUTO_ARCHIVE_DAYS: int,
# }
CONF_CARRIERS: Final = "carriers"
CONF_PACKAGES: Final = "packages"
CONF_POLL_INTERVAL: Final = "poll_interval_minutes"
CONF_AUTO_ARCHIVE_DAYS: Final = "auto_archive_days"

# Per-carrier credential field names.
CONF_CLIENT_ID: Final = "client_id"
CONF_CLIENT_SECRET: Final = "client_secret"
CONF_API_KEY: Final = "api_key"
CONF_ACCOUNT_NUMBER: Final = "account_number"

# Package dict field names (one entry per tracked parcel, stored in
# entry.options[CONF_PACKAGES]).
PKG_ID: Final = "id"
PKG_TRACKING_NUMBER: Final = "tracking_number"
PKG_CARRIER: Final = "carrier"
PKG_NAME: Final = "name"
PKG_ADDED_AT: Final = "added_at"
PKG_ARCHIVED: Final = "archived"

DEFAULT_POLL_INTERVAL: Final = 30
MIN_POLL_INTERVAL: Final = 10
MAX_POLL_INTERVAL: Final = 1440

DEFAULT_AUTO_ARCHIVE_DAYS: Final = 5
MIN_AUTO_ARCHIVE_DAYS: Final = 0
MAX_AUTO_ARCHIVE_DAYS: Final = 90

# Services.
SERVICE_ADD_PACKAGE: Final = "add_package"
SERVICE_REMOVE_PACKAGE: Final = "remove_package"
SERVICE_REFRESH: Final = "refresh"

ATTR_TRACKING_NUMBER: Final = "tracking_number"
ATTR_CARRIER: Final = "carrier"
ATTR_NAME: Final = "name"
ATTR_ENTITY_ID: Final = "entity_id"

EVENT_STATUS_CHANGED: Final = "package_tracker_status_changed"

DIAGNOSTIC_REDACT: Final = [
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_API_KEY,
    CONF_ACCOUNT_NUMBER,
    "access_token",
    "authorization",
    "unique_id",
    PKG_ID,
    PKG_TRACKING_NUMBER,
    PKG_NAME,
]
