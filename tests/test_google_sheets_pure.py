"""
Tests for pure functions in google_sheets.py that require no API calls.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from google_sheets import normalize_phone


# ---------------------------------------------------------------------------
# normalize_phone
# ---------------------------------------------------------------------------

class TestNormalizePhone:
    def test_plus7_format_unchanged(self):
        assert normalize_phone("+79161234567") == "+79161234567"

    def test_8_prefix_converts_to_plus7(self):
        assert normalize_phone("89161234567") == "+79161234567"

    def test_7_prefix_converts_to_plus7(self):
        assert normalize_phone("79161234567") == "+79161234567"

    def test_10_digits_adds_plus7(self):
        assert normalize_phone("9161234567") == "+79161234567"

    def test_different_valid_numbers(self):
        assert normalize_phone("89991112233") == "+79991112233"
        assert normalize_phone("+79991112233") == "+79991112233"

    def test_numeric_input(self):
        assert normalize_phone(79161234567) == "+79161234567"

    def test_unrecognized_format_returned_stripped(self):
        result = normalize_phone("invalid")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# normalize_phone consistency with normalize_phone_input
# ---------------------------------------------------------------------------

class TestPhoneNormalizationConsistency:
    """Both normalization functions should produce the same result for common inputs."""

    def test_8_prefix_consistent(self):
        from validators import normalize_phone_input
        raw = "89161234567"
        assert normalize_phone(raw) == normalize_phone_input(raw)

    def test_plus7_prefix_consistent(self):
        from validators import normalize_phone_input
        raw = "+79161234567"
        assert normalize_phone(raw) == normalize_phone_input(raw)

    def test_10_digits_consistent(self):
        from validators import normalize_phone_input
        raw = "9161234567"
        assert normalize_phone(raw) == normalize_phone_input(raw)
