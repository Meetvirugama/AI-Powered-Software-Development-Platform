"""Pytest suite for tested_service.py fixture.

Owner: Keval (W2 QA Foundation)
Reference: Docs/week2.md §5
"""

import pytest
from tests.fixtures.defect_fixtures.tested_service import (
    validate_email_address,
    format_display_name,
)


def test_validate_email_address_valid():
    assert validate_email_address("developer@example.com") is True
    assert validate_email_address("user.name+tag@sub.domain.org") is True


def test_validate_email_address_invalid():
    assert validate_email_address("") is False
    assert validate_email_address("missing-at-sign.com") is False
    assert validate_email_address(None) is False  # type: ignore


def test_format_display_name():
    assert format_display_name("Ada", "Lovelace") == "Ada Lovelace"
    assert format_display_name("Alan", "Turing", "Dr.") == "Dr. Alan Turing"
    assert format_display_name("Grace", "Hopper", "") == "Grace Hopper"
