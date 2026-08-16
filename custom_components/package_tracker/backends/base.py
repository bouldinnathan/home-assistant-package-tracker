"""Base class and shared exceptions for carrier tracking backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import TrackingResult


class TrackingBackendError(Exception):
    """Raised when a backend cannot produce a tracking result this cycle."""


class TrackingAuthError(TrackingBackendError):
    """Raised when a backend's credentials are missing, invalid, or expired."""


class TrackingBackend(ABC):
    """One carrier (or aggregator) tracking client.

    Every backend normalizes its carrier's own status vocabulary to
    :class:`~custom_components.package_tracker.models.PackageStatus` before
    returning, so callers never need carrier-specific branching.
    """

    carrier: str
    source: str

    @abstractmethod
    async def async_track(self, tracking_number: str) -> TrackingResult:
        """Return the current tracking status for one tracking number.

        Raises :class:`TrackingBackendError` (or the more specific
        :class:`TrackingAuthError`) if the carrier's API could not be reached
        or returned something this client doesn't understand.
        """
