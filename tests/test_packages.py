"""Tests for the pure package list helpers used by both the options flow and the services."""

from __future__ import annotations

from custom_components.package_tracker.const import CARRIER_AUTO, CARRIER_UPS, PKG_ARCHIVED, PKG_NAME
from custom_components.package_tracker.packages import (
    build_package,
    find_package,
    resolved_carrier,
    with_added_package,
    with_archived_package,
    with_removed_package,
)


def test_build_package_normalizes_tracking_number_and_defaults_name() -> None:
    package = build_package(" 1z999aa10123456784 ")
    assert package["tracking_number"] == "1Z999AA10123456784"
    assert package[PKG_NAME] == "1Z999AA10123456784"
    assert package["carrier"] == CARRIER_AUTO
    assert package[PKG_ARCHIVED] is False
    assert package["id"]


def test_build_package_honors_explicit_carrier_and_name() -> None:
    package = build_package("1Z999AA10123456784", carrier=CARRIER_UPS, name="Birthday gift")
    assert package["carrier"] == CARRIER_UPS
    assert package[PKG_NAME] == "Birthday gift"


def test_resolved_carrier_returns_explicit_carrier_unchanged() -> None:
    package = build_package("123456789012", carrier=CARRIER_UPS)
    assert resolved_carrier(package) == CARRIER_UPS


def test_resolved_carrier_falls_back_to_detection_when_auto() -> None:
    package = build_package("1Z999AA10123456784", carrier=CARRIER_AUTO)
    assert resolved_carrier(package) == CARRIER_UPS


def test_with_added_package_appends_without_mutating_input() -> None:
    options = {"packages": []}
    package = build_package("1Z999AA10123456784")
    new_options = with_added_package(options, package)
    assert options["packages"] == []
    assert new_options["packages"] == [package]


def test_with_removed_package_drops_only_matching_id() -> None:
    a = build_package("1Z999AA10123456784")
    b = build_package("123456789012")
    options = {"packages": [a, b]}
    new_options = with_removed_package(options, a["id"])
    assert new_options["packages"] == [b]


def test_with_archived_package_marks_flag_without_removing() -> None:
    a = build_package("1Z999AA10123456784")
    options = {"packages": [a]}
    new_options = with_archived_package(options, a["id"])
    assert new_options["packages"][0][PKG_ARCHIVED] is True
    assert new_options["packages"][0]["id"] == a["id"]


def test_find_package_by_id_and_by_tracking_number() -> None:
    a = build_package("1Z999AA10123456784")
    options = {"packages": [a]}
    assert find_package(options, package_id=a["id"]) == a
    assert find_package(options, tracking_number="1z999aa10123456784") == a
    assert find_package(options, tracking_number="nope") is None
