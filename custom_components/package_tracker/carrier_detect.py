"""Best-effort carrier detection from a tracking number's shape.

There is no public, authoritative algorithm that maps a tracking number to
its carrier with certainty - length and prefix conventions overlap across
carriers, and even commercial aggregators sometimes get it wrong. This module
only offers ranked *guesses* based on well-known, widely documented format
conventions (UPS's "1Z" prefix, USPS's service-type-code prefixes, DHL's
"JJD" prefix, FedEx's typical digit lengths). Treat the top guess as a
default, not a certainty - the config flow always lets a user pick the
carrier explicitly instead of trusting auto-detection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .const import CARRIER_DHL, CARRIER_FEDEX, CARRIER_UNKNOWN, CARRIER_UPS, CARRIER_USPS


@dataclass(frozen=True, slots=True)
class CarrierGuess:
    """One candidate carrier for a tracking number, with a 0-1 confidence."""

    carrier: str
    confidence: float


# (pattern, carrier, confidence) - evaluated in order; a tracking number may
# match more than one rule (e.g. a bare 12-digit number is *only* plausible
# as FedEx here, but a 20-digit number could be USPS or FedEx), in which case
# the highest confidence seen for each carrier wins.
_RULES: tuple[tuple[re.Pattern[str], str, float], ...] = (
    (re.compile(r"^1Z[0-9A-Z]{16}$"), CARRIER_UPS, 0.98),
    (re.compile(r"^[A-Z]{2}\d{9}US$"), CARRIER_USPS, 0.9),
    (re.compile(r"^JJD\d{10,20}$"), CARRIER_DHL, 0.9),
    (re.compile(r"^DT\d{12}$"), CARRIER_FEDEX, 0.9),
    (re.compile(r"^\d{12}$"), CARRIER_FEDEX, 0.65),
    (re.compile(r"^\d{15}$"), CARRIER_FEDEX, 0.6),
    (re.compile(r"^\d{10,11}$"), CARRIER_DHL, 0.55),
)

# USPS service-type-code prefixes for the common 20/22/26-digit domestic
# formats (Priority Mail, Certified, Signature Confirmation, etc.).
_USPS_SERVICE_PREFIXES: tuple[str, ...] = (
    "9200", "9205", "9208", "9214", "9218", "9219", "9261",
    "9270", "9274", "9302", "9303", "9400", "9403", "9407",
    "9611", "9614",
)  # fmt: skip


def _normalize(raw: str) -> str:
    return re.sub(r"\s+", "", raw or "").upper()


def detect_carrier(raw: str) -> list[CarrierGuess]:
    """Return carrier guesses for ``raw``, most confident first."""
    cleaned = _normalize(raw)
    if not cleaned:
        return []

    scores: dict[str, float] = {}

    def score(carrier: str, confidence: float) -> None:
        scores[carrier] = max(scores.get(carrier, 0.0), confidence)

    for pattern, carrier, confidence in _RULES:
        if pattern.match(cleaned):
            score(carrier, confidence)

    if cleaned.isdigit() and len(cleaned) in (20, 22, 26):
        if cleaned.startswith(_USPS_SERVICE_PREFIXES):
            score(CARRIER_USPS, 0.96)
        else:
            # Long numeric strings with no recognized USPS prefix are also
            # plausible as FedEx Ground/SmartPost, just with lower confidence.
            score(CARRIER_USPS, 0.4)
            score(CARRIER_FEDEX, 0.3)

    if cleaned.isdigit() and len(cleaned) in (10, 11):
        # Overlaps with the DHL rule above; FedEx is a plausible secondary guess.
        score(CARRIER_FEDEX, 0.25)

    guesses = [CarrierGuess(carrier=carrier, confidence=round(confidence, 2)) for carrier, confidence in scores.items()]
    guesses.sort(key=lambda guess: -guess.confidence)
    return guesses


def best_guess(raw: str) -> str:
    """Return the single most likely carrier, or ``CARRIER_UNKNOWN`` if none matched."""
    guesses = detect_carrier(raw)
    return guesses[0].carrier if guesses else CARRIER_UNKNOWN
