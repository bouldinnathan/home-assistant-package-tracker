"""Data update coordinator for the Package Tracker config entry.

Polls every tracked, non-archived package on an interval. Each package gets
an ordered list of candidate backends: its native carrier backend first (if
credentials are configured for its resolved carrier), then every configured
fallback aggregator in a fixed order (17track, AfterShip, TrackingMore,
Ship24). Every candidate is assumed likely to fail on any given poll - rate
limits, outages, a changed API shape - so :meth:`PackageTrackerCoordinator._async_track_one`
tries each in turn and only gives up (falling back to the package's last
known result) once all of them have failed. A package reports
``NEEDS_CONFIGURATION`` only when there were no candidates to try at all.

A separate, much less frequent timer (registered in ``__init__.py``, not
here) calls :meth:`PackageTrackerCoordinator.async_prune_delivered` to
archive packages that have stayed delivered past the configured grace
period - that mutates the config entry itself, which triggers a reload, so
it deliberately does not happen inside this coordinator's own update cycle.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .backends.aftership import AfterShipBackend
from .backends.base import TrackingAuthError, TrackingBackend, TrackingBackendError
from .backends.dhl import DhlBackend
from .backends.fedex import FedexBackend
from .backends.seventeentrack import SeventeenTrackBackend
from .backends.ship24 import Ship24Backend
from .backends.trackingmore import TrackingMoreBackend
from .backends.ups import UpsBackend
from .backends.usps import UspsBackend
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
    EVENT_STATUS_CHANGED,
    NATIVE_CARRIERS,
    PKG_ARCHIVED,
    PKG_CARRIER,
    PKG_ID,
    PKG_NAME,
    PKG_TRACKING_NUMBER,
)
from .models import PackageStatus, TrackingResult
from .packages import resolved_carrier, with_archived_package
from .storage import TrackingStore

_LOGGER = logging.getLogger(__name__)
_BACKEND_TIMEOUT = 30


@dataclass(frozen=True, slots=True)
class TrackedPackage:
    """One package definition merged with its latest tracking result."""

    id: str
    tracking_number: str
    name: str
    carrier: str
    resolved_carrier: str
    result: TrackingResult


class PackageTrackerCoordinator(DataUpdateCoordinator[dict[str, TrackedPackage]]):
    """Polls every configured, non-archived package once per update interval."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._backends: dict[str, TrackingBackend] = _build_native_backends(hass, entry.options)
        self._fallback_chain: list[TrackingBackend] = _build_fallback_chain(hass, entry.options)
        self._delivered_since: dict[str, datetime] = {}
        self._store = TrackingStore(hass, entry.entry_id)

        poll_minutes = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=poll_minutes),
            config_entry=entry,
        )

    async def _async_setup(self) -> None:
        cached, delivered_since = await self._store.async_load_tracking()
        self.data = {
            package[PKG_ID]: _tracked_package(package, cached[package[PKG_ID]])
            for package in self.config_entry.options.get(CONF_PACKAGES, [])
            if not package.get(PKG_ARCHIVED) and package[PKG_ID] in cached
        }
        self._delivered_since = {
            package_id: since for package_id, since in delivered_since.items() if package_id in self.data
        }

    async def _async_update_data(self) -> dict[str, TrackedPackage]:
        packages = [pkg for pkg in self.config_entry.options.get(CONF_PACKAGES, []) if not pkg.get(PKG_ARCHIVED)]
        previous = self.data or {}
        results: dict[str, TrackedPackage] = {}

        for package in packages:
            package_id = package[PKG_ID]
            tracking_number = package[PKG_TRACKING_NUMBER]
            carrier = resolved_carrier(package)
            native = self._backends.get(carrier)
            candidates = [native, *self._fallback_chain] if native is not None else list(self._fallback_chain)

            if not candidates:
                result = TrackingResult(
                    status=PackageStatus.NEEDS_CONFIGURATION,
                    status_detail=f"No {carrier} credentials and no fallback aggregators configured",
                    source="none",
                    resolved_carrier=carrier,
                )
            else:
                result = await self._async_track_one(candidates, tracking_number, carrier, previous.get(package_id))

            tracked = _tracked_package(package, result)
            results[package_id] = tracked
            self._record_delivered_since(package_id, result.status)
            self._maybe_fire_status_changed(previous.get(package_id), tracked)

        self._delivered_since = {key: value for key, value in self._delivered_since.items() if key in results}
        await self._store.async_save_tracking(
            {package_id: tracked.result for package_id, tracked in results.items()}, self._delivered_since
        )
        return results

    async def _async_track_one(
        self,
        candidates: list[TrackingBackend],
        tracking_number: str,
        carrier: str,
        previous: TrackedPackage | None,
    ) -> TrackingResult:
        """Try each candidate backend in order; assume any of them can fail.

        Every candidate - the native backend and each configured fallback
        aggregator - gets one attempt per poll. The first one to succeed
        wins. If every single one fails (or raises something unexpected),
        this fails soft: it returns the package's last known result rather
        than erroring the sensor out, exactly like the single-backend
        behavior this replaced.
        """
        for backend in candidates:
            try:
                async with asyncio.timeout(_BACKEND_TIMEOUT):
                    return await backend.async_track(tracking_number)
            except TimeoutError:
                _LOGGER.warning("Tracking request via %s timed out", backend.source)
            except TrackingAuthError as err:
                _LOGGER.warning("Tracking auth failed for %s via %s: %s", tracking_number, backend.source, err)
            except TrackingBackendError as err:
                _LOGGER.warning("Tracking %s via %s failed: %s", tracking_number, backend.source, err)
            except Exception:
                _LOGGER.error("Unexpected error tracking %s via %s", tracking_number, backend.source, exc_info=True)

        _LOGGER.warning(
            "All %d tracking backend(s) failed for %s this cycle", len(candidates), tracking_number
        )
        if previous is not None:
            return previous.result
        return TrackingResult(
            status=PackageStatus.UNKNOWN,
            status_detail="Tracking failed and no prior result is available yet",
            source="error",
            resolved_carrier=carrier,
        )

    def _record_delivered_since(self, package_id: str, status: PackageStatus) -> None:
        if status == PackageStatus.DELIVERED:
            self._delivered_since.setdefault(package_id, dt_util.utcnow())
        else:
            self._delivered_since.pop(package_id, None)

    def _maybe_fire_status_changed(self, previous: TrackedPackage | None, tracked: TrackedPackage) -> None:
        if previous is None or previous.result.status == tracked.result.status:
            return
        self.hass.bus.async_fire(
            EVENT_STATUS_CHANGED,
            {
                "package_id": tracked.id,
                "tracking_number": tracked.tracking_number,
                "name": tracked.name,
                "carrier": tracked.resolved_carrier,
                "previous_status": previous.result.status.value,
                "status": tracked.result.status.value,
                "status_detail": tracked.result.status_detail,
            },
        )

    async def async_prune_delivered(self) -> list[str]:
        """Archive packages delivered longer ago than the configured grace period.

        Called from a separate periodic timer (see ``__init__.py``), not from
        ``_async_update_data`` - it mutates the config entry, which triggers a
        reload, and doing that from inside the coordinator's own protected
        update path would cancel the very update that triggered it.
        """
        auto_archive_days = self.config_entry.options.get(CONF_AUTO_ARCHIVE_DAYS, DEFAULT_AUTO_ARCHIVE_DAYS)
        if auto_archive_days <= 0:
            return []

        cutoff = dt_util.utcnow() - timedelta(days=auto_archive_days)
        to_archive = [pkg_id for pkg_id, since in self._delivered_since.items() if since <= cutoff]
        if not to_archive:
            return []

        options = dict(self.config_entry.options)
        for package_id in to_archive:
            options = with_archived_package(options, package_id)
        self.hass.config_entries.async_update_entry(self.config_entry, options=options)
        _LOGGER.info("Auto-archived %d package(s) delivered over %d day(s) ago", len(to_archive), auto_archive_days)
        return to_archive


def _tracked_package(package: dict[str, Any], result: TrackingResult) -> TrackedPackage:
    """Prefer the backend's carrier identification over an ambiguous format guess."""
    return TrackedPackage(
        id=package[PKG_ID],
        tracking_number=package[PKG_TRACKING_NUMBER],
        name=package.get(PKG_NAME) or package[PKG_TRACKING_NUMBER],
        carrier=package.get(PKG_CARRIER, CARRIER_AUTO),
        resolved_carrier=result.resolved_carrier if result.resolved_carrier in NATIVE_CARRIERS else resolved_carrier(package),
        result=result,
    )


def _build_native_backends(hass: HomeAssistant, options: dict[str, Any]) -> dict[str, TrackingBackend]:
    session = async_get_clientsession(hass)
    carriers: dict[str, Any] = options.get(CONF_CARRIERS, {})
    backends: dict[str, TrackingBackend] = {}

    ups = carriers.get(CARRIER_UPS) or {}
    if ups.get(CONF_CLIENT_ID) and ups.get(CONF_CLIENT_SECRET):
        backends[CARRIER_UPS] = UpsBackend(session, client_id=ups[CONF_CLIENT_ID], client_secret=ups[CONF_CLIENT_SECRET])

    fedex = carriers.get(CARRIER_FEDEX) or {}
    if fedex.get(CONF_CLIENT_ID) and fedex.get(CONF_CLIENT_SECRET):
        backends[CARRIER_FEDEX] = FedexBackend(
            session, client_id=fedex[CONF_CLIENT_ID], client_secret=fedex[CONF_CLIENT_SECRET]
        )

    dhl = carriers.get(CARRIER_DHL) or {}
    if dhl.get(CONF_API_KEY):
        backends[CARRIER_DHL] = DhlBackend(session, api_key=dhl[CONF_API_KEY])

    usps = carriers.get(CARRIER_USPS) or {}
    if usps.get(CONF_CLIENT_ID) and usps.get(CONF_CLIENT_SECRET):
        backends[CARRIER_USPS] = UspsBackend(
            session, client_id=usps[CONF_CLIENT_ID], client_secret=usps[CONF_CLIENT_SECRET]
        )

    return backends


def _build_fallback_chain(hass: HomeAssistant, options: dict[str, Any]) -> list[TrackingBackend]:
    """Build every configured fallback aggregator, in the fixed priority order.

    Each one is optional and independent - configure just 17track, all four,
    or any subset. Whichever are configured get tried in this order for any
    package that needs a fallback.
    """
    session = async_get_clientsession(hass)
    carriers: dict[str, Any] = options.get(CONF_CARRIERS, {}) or {}
    chain: list[TrackingBackend] = []

    seventeentrack = carriers.get(BACKEND_SEVENTEENTRACK) or {}
    if seventeentrack.get(CONF_API_KEY):
        chain.append(SeventeenTrackBackend(session, api_key=seventeentrack[CONF_API_KEY]))

    aftership = carriers.get(BACKEND_AFTERSHIP) or {}
    if aftership.get(CONF_API_KEY):
        chain.append(AfterShipBackend(session, api_key=aftership[CONF_API_KEY]))

    trackingmore = carriers.get(BACKEND_TRACKINGMORE) or {}
    if trackingmore.get(CONF_API_KEY):
        chain.append(TrackingMoreBackend(session, api_key=trackingmore[CONF_API_KEY]))

    ship24 = carriers.get(BACKEND_SHIP24) or {}
    if ship24.get(CONF_API_KEY):
        chain.append(Ship24Backend(session, api_key=ship24[CONF_API_KEY]))

    return chain
