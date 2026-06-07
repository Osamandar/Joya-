"""
Tests for validators.py — phone normalization, field validation, employee edit logic.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

from validators import (
    normalize_phone_input,
    parse_yes_no,
    resolve_edit_field,
    resolve_admin_role,
    find_single_employee,
    _apply_employee_edit,
)
from config import COL_EXPIRY, COL_PHONE, COL_POSITION, COL_SUBDIVISION, COL_IN_MAIN, COL_IN_SUB


# ---------------------------------------------------------------------------
# normalize_phone_input
# ---------------------------------------------------------------------------

class TestNormalizePhoneInput:
    def test_plus7_format_unchanged(self):
        assert normalize_phone_input("+79161234567") == "+79161234567"

    def test_8_prefix_converts_to_plus7(self):
        assert normalize_phone_input("89161234567") == "+79161234567"

    def test_7_prefix_converts_to_plus7(self):
        assert normalize_phone_input("79161234567") == "+79161234567"

    def test_10_digits_adds_plus7(self):
        assert normalize_phone_input("9161234567") == "+79161234567"

    def test_spaces_and_dashes_stripped(self):
        assert normalize_phone_input("+7 916 123-45-67") == "+79161234567"

    def test_parentheses_stripped(self):
        assert normalize_phone_input("+7(916)1234567") == "+79161234567"

    def test_too_short_returns_none(self):
        assert normalize_phone_input("12345") is None

    def test_empty_returns_none(self):
        assert normalize_phone_input("") is None

    def test_letters_returns_none(self):
        assert normalize_phone_input("not-a-phone") is None

    def test_9_digits_returns_none(self):
        assert normalize_phone_input("916123456") is None

    def test_12_digits_returns_none(self):
        assert normalize_phone_input("791612345678") is None


# ---------------------------------------------------------------------------
# parse_yes_no
# ---------------------------------------------------------------------------

class TestParseYesNo:
    @pytest.mark.parametrize("value", ["да", "yes", "y", "1", "true", "Да", "YES", "True"])
    def test_yes_variants(self, value):
        assert parse_yes_no(value) == "да"

    @pytest.mark.parametrize("value", ["нет", "no", "n", "0", "false", "Нет", "NO", "False"])
    def test_no_variants(self, value):
        assert parse_yes_no(value) == "нет"

    @pytest.mark.parametrize("value", ["maybe", "", "2", "ок", "нет нет"])
    def test_invalid_returns_none(self, value):
        assert parse_yes_no(value) is None


# ---------------------------------------------------------------------------
# resolve_edit_field
# ---------------------------------------------------------------------------

class TestResolveEditField:
    @pytest.mark.parametrize("alias,expected", [
        ("дата", "expiry"),
        ("срок", "expiry"),
        ("expiry", "expiry"),
        ("date", "expiry"),
        ("должность", "position"),
        ("position", "position"),
        ("подразделение", "subdivision"),
        ("subdivision", "subdivision"),
        ("телефон", "phone"),
        ("phone", "phone"),
        ("главная", "main_group"),
        ("main", "main_group"),
        ("maingroup", "main_group"),
        ("подгруппа", "sub_group"),
        ("группа", "sub_group"),
        ("sub", "sub_group"),
        ("subgroup", "sub_group"),
    ])
    def test_known_aliases(self, alias, expected):
        assert resolve_edit_field(alias) == expected

    def test_case_insensitive(self):
        assert resolve_edit_field("ДАТА") == "expiry"
        assert resolve_edit_field("Должность") == "position"

    def test_unknown_field_returns_none(self):
        assert resolve_edit_field("nonexistent") is None
        assert resolve_edit_field("") is None


# ---------------------------------------------------------------------------
# resolve_admin_role
# ---------------------------------------------------------------------------

class TestResolveAdminRole:
    @pytest.mark.parametrize("alias", ["admin", "админ"])
    def test_admin_aliases(self, alias):
        assert resolve_admin_role(alias) == "admin"

    @pytest.mark.parametrize("alias", ["owner", "владелец"])
    def test_owner_aliases(self, alias):
        assert resolve_admin_role(alias) == "owner"

    def test_unknown_returns_none(self):
        assert resolve_admin_role("superuser") is None
        assert resolve_admin_role("") is None


# ---------------------------------------------------------------------------
# find_single_employee
# ---------------------------------------------------------------------------

class TestFindSingleEmployee:
    def test_not_found_returns_error(self):
        with patch("validators.search_employees", return_value=[]):
            emp, err = find_single_employee("Иванов")
            assert emp is None
            assert err is not None
            assert "не найден" in err

    def test_single_match_returns_employee(self):
        employee = {"ФИО": "Иванов И.И.", "row_number": 3}
        with patch("validators.search_employees", return_value=[employee]):
            emp, err = find_single_employee("Иванов")
            assert emp == employee
            assert err is None

    def test_multiple_matches_returns_error(self):
        employees = [
            {"ФИО": "Иванов А.А.", "Телефон": "+79111", "Должность": "Повар"},
            {"ФИО": "Иванов Б.Б.", "Телефон": "+79222", "Должность": "Кассир"},
        ]
        with patch("validators.search_employees", return_value=employees):
            emp, err = find_single_employee("Иванов")
            assert emp is None
            assert "несколько" in err

    def test_more_than_10_matches_shows_count(self):
        employees = [
            {"ФИО": f"Иванов {i}", "Телефон": f"+7916{i:07}", "Должность": "Повар"}
            for i in range(15)
        ]
        with patch("validators.search_employees", return_value=employees):
            emp, err = find_single_employee("Иванов")
            assert emp is None
            assert "15" in err


# ---------------------------------------------------------------------------
# _apply_employee_edit
# ---------------------------------------------------------------------------

class TestApplyEmployeeEditExpiry:
    def test_future_date_clears_row_status(self):
        with patch("validators.update_employee_cell") as mock_update, \
             patch("validators.set_row_red") as mock_red, \
             patch("validators.set_row_default") as mock_default, \
             patch("validators.set_employee_status"), \
             patch("validators.clear_employee_status") as mock_clear:
            result = _apply_employee_edit(5, "expiry", "31-12-2030")
            assert result is None
            mock_update.assert_called_once_with(5, COL_EXPIRY, "2030-12-31")
            mock_default.assert_called_once_with(5)
            mock_clear.assert_called_once_with(5)
            mock_red.assert_not_called()

    def test_past_date_marks_row_red(self):
        with patch("validators.update_employee_cell"), \
             patch("validators.set_row_red") as mock_red, \
             patch("validators.set_row_default") as mock_default, \
             patch("validators.set_employee_status") as mock_status, \
             patch("validators.clear_employee_status"):
            result = _apply_employee_edit(5, "expiry", "01-01-2000")
            assert result is None
            mock_red.assert_called_once_with(5)
            mock_status.assert_called_once_with(5, "expired")
            mock_default.assert_not_called()

    def test_invalid_date_returns_error(self):
        result = _apply_employee_edit(5, "expiry", "не-дата")
        assert result is not None
        assert "формат" in result.lower() or "гггг" in result.lower()

    def test_wrong_date_format_returns_error(self):
        result = _apply_employee_edit(5, "expiry", "2030-12-31")
        assert result is not None


class TestApplyEmployeeEditPhone:
    def test_valid_phone_updates_cell(self):
        with patch("validators.update_employee_cell") as mock_update:
            result = _apply_employee_edit(5, "phone", "+79161234567")
            assert result is None
            mock_update.assert_called_once_with(5, COL_PHONE, "+79161234567")

    def test_8_prefix_phone_accepted(self):
        with patch("validators.update_employee_cell") as mock_update:
            result = _apply_employee_edit(5, "phone", "89161234567")
            assert result is None

    def test_invalid_phone_returns_error(self):
        result = _apply_employee_edit(5, "phone", "123")
        assert result is not None
        assert "формат" in result.lower()


class TestApplyEmployeeEditPosition:
    def test_valid_position_updates_cell(self):
        with patch("validators.update_employee_cell") as mock_update, \
             patch("validators.resolve_subdivision", return_value=None):
            result = _apply_employee_edit(5, "position", "Повар")
            assert result is None
            mock_update.assert_any_call(5, COL_POSITION, "Повар")

    def test_position_with_auto_subdivision(self):
        with patch("validators.update_employee_cell") as mock_update, \
             patch("validators.resolve_subdivision", return_value="Кухня"):
            result = _apply_employee_edit(5, "position", "Повар")
            assert result is None
            calls = [c.args for c in mock_update.call_args_list]
            assert (5, COL_POSITION, "Повар") in calls
            assert (5, COL_SUBDIVISION, "Кухня") in calls


class TestApplyEmployeeEditSubdivision:
    def test_valid_subdivision_updates_cell(self):
        with patch("validators.get_subdivision_names", return_value=["Кухня", "Касса"]), \
             patch("validators.update_employee_cell") as mock_update:
            result = _apply_employee_edit(5, "subdivision", "Кухня")
            assert result is None
            mock_update.assert_called_once_with(5, COL_SUBDIVISION, "Кухня")

    def test_invalid_subdivision_returns_error(self):
        with patch("validators.get_subdivision_names", return_value=["Кухня", "Касса"]):
            result = _apply_employee_edit(5, "subdivision", "Несуществующее")
            assert result is not None
            assert "Кухня" in result

    def test_empty_sheet_returns_error(self):
        """Regression: empty subdivisions list must not silently skip validation."""
        with patch("validators.get_subdivision_names", return_value=[]):
            result = _apply_employee_edit(5, "subdivision", "Кухня")
            assert result is not None
            assert "загрузить" in result.lower()

    def test_dash_clears_subdivision(self):
        with patch("validators.get_subdivision_names", return_value=["Кухня"]), \
             patch("validators.update_employee_cell") as mock_update:
            result = _apply_employee_edit(5, "subdivision", "-")
            assert result is None
            mock_update.assert_called_once_with(5, COL_SUBDIVISION, "")

    def test_empty_sheet_with_clear_value_is_allowed(self):
        """Clearing subdivision (dash/пусто) is allowed even when sheet is empty."""
        with patch("validators.get_subdivision_names", return_value=[]), \
             patch("validators.update_employee_cell") as mock_update:
            result = _apply_employee_edit(5, "subdivision", "-")
            assert result is None
            mock_update.assert_called_once_with(5, COL_SUBDIVISION, "")


class TestApplyEmployeeEditGroups:
    def test_main_group_yes(self):
        with patch("validators.update_employee_cell") as mock_update:
            result = _apply_employee_edit(5, "main_group", "да")
            assert result is None
            mock_update.assert_called_once_with(5, COL_IN_MAIN, "да")

    def test_main_group_no(self):
        with patch("validators.update_employee_cell") as mock_update:
            result = _apply_employee_edit(5, "main_group", "нет")
            assert result is None
            mock_update.assert_called_once_with(5, COL_IN_MAIN, "нет")

    def test_main_group_invalid(self):
        result = _apply_employee_edit(5, "main_group", "maybe")
        assert result is not None

    def test_sub_group_yes(self):
        with patch("validators.update_employee_cell") as mock_update:
            result = _apply_employee_edit(5, "sub_group", "да")
            assert result is None
            mock_update.assert_called_once_with(5, COL_IN_SUB, "да")

    def test_sub_group_invalid(self):
        result = _apply_employee_edit(5, "sub_group", "wrong")
        assert result is not None
