"""Shared helper for mapping an aggregator's free-text carrier name back to our carrier ids.

Every aggregator fallback (17track, AfterShip, TrackingMore, Ship24) reports
which carrier it thinks handled a package using its own vocabulary (a name
string, a slug, ...). This does simple substring matching against that text
so results carry our normalized carrier id instead of four different
aggregator-specific spellings.
"""

from __future__ import annotations

from ..const import CARRIER_DHL, CARRIER_FEDEX, CARRIER_UNKNOWN, CARRIER_UPS, CARRIER_USPS


def guess_carrier_from_name(name: str | None) -> str:
    """Return one of our carrier ids based on substring matches in ``name``, or unknown."""
    if not name:
        return CARRIER_UNKNOWN
    normalized = name.casefold()
    if "ups" in normalized:
        return CARRIER_UPS
    if "fedex" in normalized:
        return CARRIER_FEDEX
    if "dhl" in normalized:
        return CARRIER_DHL
    if "usps" in normalized or "united states postal" in normalized:
        return CARRIER_USPS
    return CARRIER_UNKNOWN
