"""Shared data models for package tracking state.

Every carrier backend (native UPS/FedEx/DHL/USPS clients and the 17track
fallback) normalizes its own status vocabulary down to :class:`PackageStatus`
so entities, automations, and the notification blueprint only ever deal with
one small set of states regardless of which backend actually answered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class PackageStatus(StrEnum):
    """Normalized lifecycle state of a tracked package."""

    UNKNOWN = "unknown"
    INFO_RECEIVED = "info_received"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    AVAILABLE_FOR_PICKUP = "available_for_pickup"
    DELIVERED = "delivered"
    DELIVERY_EXCEPTION = "delivery_exception"
    RETURNED = "returned"
    NEEDS_CONFIGURATION = "needs_configuration"


@dataclass(frozen=True, slots=True)
class TrackingEvent:
    """One scan/status event in a package's history, newest first."""

    timestamp: datetime | None
    description: str
    location: str | None = None
    status: PackageStatus = PackageStatus.UNKNOWN


@dataclass(frozen=True, slots=True)
class TrackingResult:
    """Normalized result of tracking one package with one backend."""

    status: PackageStatus
    status_detail: str
    source: str
    resolved_carrier: str
    estimated_delivery: datetime | None = None
    events: tuple[TrackingEvent, ...] = field(default_factory=tuple)

    @property
    def latest_event(self) -> TrackingEvent | None:
        """Return the most recent event, if any."""
        return self.events[0] if self.events else None
