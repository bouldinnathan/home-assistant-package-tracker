"""Pytest configuration: HA test harness, plus a minimal fake aiohttp session for backend tests."""

from __future__ import annotations

import os
from typing import Any

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture
def hass_config_dir() -> str:
    """Point the HA test harness at this repo's custom_components, not the plugin's own."""
    return os.path.join(os.path.dirname(__file__), "testing_config")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let every test load custom_components/package_tracker through the real loader."""
    yield


class FakeResponse:
    """Stand-in for an aiohttp response, usable as ``async with session.get(...) as response``."""

    def __init__(self, *, status: int, json_body: Any) -> None:
        self.status = status
        self._json_body = json_body

    async def json(self, content_type: str | None = None) -> Any:
        return self._json_body

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class FakeSession:
    """Minimal aiohttp.ClientSession stand-in for backend unit tests.

    Queue canned JSON responses per HTTP method with :meth:`queue_json` in
    call order; ``get``/``post`` pop them FIFO. This mirrors how each backend
    issues exactly one request per logical step (e.g. an OAuth token fetch,
    then the tracking call itself), without needing a full HTTP mocking
    library for tests that don't otherwise touch Home Assistant.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._queued: dict[str, list[FakeResponse]] = {"GET": [], "POST": []}

    def queue_json(self, method: str, json_body: Any, *, status: int = 200) -> None:
        self._queued[method.upper()].append(FakeResponse(status=status, json_body=json_body))

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("GET", url, kwargs))
        return self._queued["GET"].pop(0)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("POST", url, kwargs))
        return self._queued["POST"].pop(0)


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession()
