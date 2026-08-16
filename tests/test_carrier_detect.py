"""Tests for the best-effort carrier detection heuristics.

Tracking numbers used here are synthetic (structurally valid shapes, not
real shipments) purely to exercise each format rule.
"""

from __future__ import annotations

from custom_components.package_tracker.carrier_detect import best_guess, detect_carrier
from custom_components.package_tracker.const import (
    CARRIER_DHL,
    CARRIER_FEDEX,
    CARRIER_UNKNOWN,
    CARRIER_UPS,
    CARRIER_USPS,
)


def test_ups_1z_prefix_detected_with_high_confidence() -> None:
    guesses = detect_carrier("1Z999AA10123456784")
    assert guesses[0].carrier == CARRIER_UPS
    assert guesses[0].confidence >= 0.9


def test_ups_detection_is_case_and_whitespace_insensitive() -> None:
    assert best_guess(" 1z999aa1 0123456784 ") == CARRIER_UPS


def test_usps_service_prefix_detected() -> None:
    # 22 digits starting with the "9400" USPS service-type-code prefix.
    assert best_guess("9400111899223197428490") == CARRIER_USPS


def test_usps_international_s10_format_detected() -> None:
    assert best_guess("EC123456785US") == CARRIER_USPS


def test_dhl_jjd_prefix_detected() -> None:
    assert best_guess("JJD0123456789012345") == CARRIER_DHL


def test_dhl_ten_digit_numeric_is_primary_guess_over_fedex() -> None:
    guesses = detect_carrier("1234567890")
    by_carrier = {guess.carrier: guess.confidence for guess in guesses}
    assert by_carrier[CARRIER_DHL] > by_carrier[CARRIER_FEDEX]


def test_fedex_twelve_digit_detected() -> None:
    assert best_guess("123456789012") == CARRIER_FEDEX


def test_fedex_fifteen_digit_detected() -> None:
    assert best_guess("123456789012345") == CARRIER_FEDEX


def test_unrecognized_length_returns_unknown() -> None:
    assert best_guess("42") == CARRIER_UNKNOWN


def test_empty_input_returns_unknown() -> None:
    assert best_guess("") == CARRIER_UNKNOWN
    assert detect_carrier("") == []


def test_long_numeric_with_unrecognized_prefix_offers_both_usps_and_fedex() -> None:
    guesses = detect_carrier("1111111111111111111111")  # 22 digits, no known USPS prefix
    carriers = {guess.carrier for guess in guesses}
    assert {CARRIER_USPS, CARRIER_FEDEX} <= carriers
