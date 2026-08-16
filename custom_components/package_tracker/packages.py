"""Pure helpers for building and mutating the package list stored in config entry options.

Kept side-effect free (no ``hass`` access, no I/O) so both the options flow
and the ``add_package``/``remove_package`` services can share exactly one
implementation of "what a package dict looks like" and "how the list is
edited," and so the shape can be unit tested without spinning up Home
Assistant at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .carrier_detect import best_guess
from .const import (
    CARRIER_AUTO,
    CONF_PACKAGES,
    PKG_ADDED_AT,
    PKG_ARCHIVED,
    PKG_CARRIER,
    PKG_ID,
    PKG_NAME,
    PKG_TRACKING_NUMBER,
)


def normalize_tracking_number(raw: str) -> str:
    """Strip whitespace and uppercase a pasted tracking number for consistent storage/lookup."""
    return "".join(raw.split()).upper()


def build_package(tracking_number: str, *, carrier: str = CARRIER_AUTO, name: str | None = None) -> dict[str, Any]:
    """Build a new package dict ready to append to ``options[CONF_PACKAGES]``."""
    number = normalize_tracking_number(tracking_number)
    return {
        PKG_ID: uuid.uuid4().hex,
        PKG_TRACKING_NUMBER: number,
        PKG_CARRIER: carrier,
        PKG_NAME: name or number,
        PKG_ADDED_AT: datetime.now(UTC).isoformat(),
        PKG_ARCHIVED: False,
    }


def resolved_carrier(package: dict[str, Any]) -> str:
    """Return the package's explicit carrier, or a best-guess if it's set to auto-detect."""
    carrier = package.get(PKG_CARRIER, CARRIER_AUTO)
    if carrier != CARRIER_AUTO:
        return carrier
    return best_guess(package[PKG_TRACKING_NUMBER])


def find_package(options: dict[str, Any], *, package_id: str | None = None, tracking_number: str | None = None) -> dict[str, Any] | None:
    """Find a package by id or (normalized) tracking number."""
    normalized_number = normalize_tracking_number(tracking_number) if tracking_number else None
    for package in options.get(CONF_PACKAGES, []):
        if package_id is not None and package[PKG_ID] == package_id:
            return package
        if normalized_number is not None and package[PKG_TRACKING_NUMBER] == normalized_number:
            return package
    return None


def with_added_package(options: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    """Return new options with ``package`` appended."""
    packages = [*options.get(CONF_PACKAGES, []), package]
    return {**options, CONF_PACKAGES: packages}


def with_removed_package(options: dict[str, Any], package_id: str) -> dict[str, Any]:
    """Return new options with the package matching ``package_id`` removed."""
    packages = [pkg for pkg in options.get(CONF_PACKAGES, []) if pkg[PKG_ID] != package_id]
    return {**options, CONF_PACKAGES: packages}


def with_archived_package(options: dict[str, Any], package_id: str, *, archived: bool = True) -> dict[str, Any]:
    """Return new options with the package matching ``package_id`` marked archived (or un-archived)."""
    packages = [
        {**pkg, PKG_ARCHIVED: archived} if pkg[PKG_ID] == package_id else pkg
        for pkg in options.get(CONF_PACKAGES, [])
    ]
    return {**options, CONF_PACKAGES: packages}
