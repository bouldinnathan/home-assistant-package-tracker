"""Shared OAuth2 client-credentials token caching for UPS/FedEx/USPS.

All three of those carriers' modern tracking APIs authenticate with the
OAuth2 client-credentials grant (an app-level client_id/client_secret, no
end-user login or redirect involved). This wraps the fetch-and-cache logic
once instead of duplicating it in each backend.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from .base import TrackingAuthError

_LOGGER = logging.getLogger(__name__)

# Refresh this many seconds before the token's stated expiry, so a token that
# was valid when fetched doesn't expire mid-flight on the tracking request
# that immediately follows.
_EXPIRY_SAFETY_MARGIN = 60
_MIN_TTL = 30


class OAuthClientCredentials:
    """Fetches and caches a bearer token via the OAuth2 client-credentials grant."""

    def __init__(self, session: aiohttp.ClientSession, *, token_url: str) -> None:
        self._session = session
        self._token_url = token_url
        self._token: str | None = None
        self._expires_at: float = 0.0

    async def async_get_token(self, *, force_refresh: bool = False, **request_kwargs: Any) -> str:
        """Return a cached bearer token, fetching a new one if missing or expired."""
        if not force_refresh and self._token is not None and time.monotonic() < self._expires_at:
            return self._token

        async with self._session.post(self._token_url, **request_kwargs) as response:
            body: dict[str, Any] = await response.json(content_type=None)
            if response.status >= 400:
                _LOGGER.debug(
                    "OAuth token request to %s failed (HTTP %s): %s", self._token_url, response.status, body
                )
                raise TrackingAuthError(f"Token request to {self._token_url} failed with HTTP {response.status}")

        token = body.get("access_token")
        if not token:
            raise TrackingAuthError(f"Token response from {self._token_url} had no access_token")

        expires_in = float(body.get("expires_in", 3600) or 3600)
        self._token = token
        self._expires_at = time.monotonic() + max(expires_in - _EXPIRY_SAFETY_MARGIN, _MIN_TTL)
        return self._token
