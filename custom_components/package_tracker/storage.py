"""Persist tracking results and delivery timers across reloads and restarts."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .models import PackageStatus, TrackingEvent, TrackingResult

_LOGGER = logging.getLogger(__name__)


class TrackingStore(Store[dict[str, Any]]):
    """Entry-owned cache, separate from options so saving never reloads the entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        super().__init__(hass, 1, f"{DOMAIN}.{entry_id}")

    async def async_load_tracking(self) -> tuple[dict[str, TrackingResult], dict[str, datetime]]:
        results: dict[str, TrackingResult] = {}
        delivered_since: dict[str, datetime] = {}
        stored = await self.async_load()
        if not isinstance(stored, dict):
            return results, delivered_since
        for package_id, cached in stored.items():
            try:
                result = dict(cached["result"])
                result["status"] = PackageStatus(result["status"])
                result["estimated_delivery"] = _parse_datetime(result.get("estimated_delivery"))
                result["events"] = tuple(
                    TrackingEvent(
                        timestamp=_parse_datetime(event["timestamp"]),
                        description=event["description"],
                        location=event["location"],
                        status=PackageStatus(event["status"]),
                    )
                    for event in result.get("events", [])
                )
                results[package_id] = TrackingResult(**result)
                since = _parse_datetime(cached.get("delivered_since"))
                if since is not None and result["status"] == PackageStatus.DELIVERED:
                    delivered_since[package_id] = since
            except (KeyError, TypeError, ValueError):
                _LOGGER.warning("Ignoring an invalid cached package result")
        return results, delivered_since

    async def async_save_tracking(
        self, results: dict[str, TrackingResult], delivered_since: dict[str, datetime]
    ) -> None:
        stored = {}
        for package_id, result in results.items():
            data = asdict(result)
            data["estimated_delivery"] = result.estimated_delivery.isoformat() if result.estimated_delivery else None
            data["events"] = [
                {**asdict(event), "timestamp": event.timestamp.isoformat() if event.timestamp else None}
                for event in result.events
            ]
            since = delivered_since.get(package_id)
            stored[package_id] = {"result": data, "delivered_since": since.isoformat() if since else None}
        await self.async_save(stored)


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or (parsed := dt_util.parse_datetime(value)) is None:
        raise ValueError("Invalid cached timestamp")
    return dt_util.as_utc(parsed)
