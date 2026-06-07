"""
Tests for formatters.py — date formatting, employee/admin card rendering,
status text generation.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import date, timedelta
from unittest.mock import patch

from formatters import (
    fmt_date,
    pd_consent_value,
    admin_role_label,
    admin_status_text,
    admin_card,
    employee_status_text,
    employee_card,
)


# ---------------------------------------------------------------------------
# fmt_date
# ---------------------------------------------------------------------------

class TestFmtDate:
    def test_valid_iso_converts_to_display(self):
        assert fmt_date("2026-12-31") == "31-12-2026"

    def test_first_of_january(self):
        assert fmt_date("2000-01-01") == "01-01-2000"

    def test_empty_string_returns_empty(self):
        assert fmt_date("") == ""

    def test_invalid_format_returned_as_is(self):
        assert fmt_date("not-a-date") == "not-a-date"

    def test_already_display_format_returned_as_is(self):
        assert fmt_date("31-12-2026") == "31-12-2026"


# ---------------------------------------------------------------------------
# pd_consent_value
# ---------------------------------------------------------------------------

class TestPdConsentValue:
    def test_starts_with_da(self):
        value = pd_consent_value()
        assert value.startswith("да ")

    def test_contains_today_date(self):
        value = pd_consent_value()
        today = date.today().strftime("%Y-%m-%d")
        assert today in value


# ---------------------------------------------------------------------------
# admin_role_label
# ---------------------------------------------------------------------------

class TestAdminRoleLabel:
    def test_admin_label_in_russian(self):
        assert admin_role_label("admin") == "админ"

    def test_owner_label_in_russian(self):
        assert admin_role_label("owner") == "владелец"

    def test_unknown_role_returned_as_is(self):
        assert admin_role_label("superuser") == "superuser"

    def test_empty_role_returns_dash(self):
        assert admin_role_label("") == "—"


# ---------------------------------------------------------------------------
# admin_status_text
# ---------------------------------------------------------------------------

class TestAdminStatusText:
    def test_developer_id_shows_owner_via_env(self):
        with patch("formatters.DEVELOPER_CHAT_ID", 12345):
            result = admin_status_text(None, 12345)
            assert "владелец" in result

    def test_no_admin_record_shows_not_granted(self):
        with patch("formatters.DEVELOPER_CHAT_ID", None):
            result = admin_status_text(None, 99999)
            assert "не выдан" in result

    def test_pending_state(self):
        admin = {"state": "pending", "role": "admin"}
        result = admin_status_text(admin, 99999)
        assert "ожидает" in result

    def test_inactive_state(self):
        admin = {"state": "inactive", "role": "admin"}
        result = admin_status_text(admin, 99999)
        assert "отключен" in result

    def test_active_admin_role(self):
        admin = {"state": "active", "role": "admin"}
        result = admin_status_text(admin, 99999)
        assert "активен" in result
        assert "админ" in result

    def test_active_owner_role(self):
        admin = {"state": "active", "role": "owner"}
        result = admin_status_text(admin, 99999)
        assert "активен" in result
        assert "владелец" in result


# ---------------------------------------------------------------------------
# admin_card
# ---------------------------------------------------------------------------

class TestAdminCard:
    def _admin(self, **kwargs) -> dict:
        base = {
            "chat_id": 123456,
            "fio": "Петров П.П.",
            "username": "petrov",
            "role": "admin",
            "subdivision": "Кухня",
            "state": "active",
            "requested_at": "2024-01-01",
            "granted_at": "2024-01-02",
        }
        base.update(kwargs)
        return base

    def test_contains_chat_id(self):
        card = admin_card(self._admin())
        assert "123456" in card

    def test_contains_fio(self):
        card = admin_card(self._admin())
        assert "Петров П.П." in card

    def test_contains_username_with_at(self):
        card = admin_card(self._admin())
        assert "@petrov" in card

    def test_empty_username_shows_dash(self):
        card = admin_card(self._admin(username=""))
        assert "—" in card

    def test_contains_role_label(self):
        card = admin_card(self._admin(role="admin"))
        assert "админ" in card

    def test_no_subdivision_shows_all(self):
        card = admin_card(self._admin(subdivision=""))
        assert "все подразделения" in card


# ---------------------------------------------------------------------------
# employee_status_text
# ---------------------------------------------------------------------------

class TestEmployeeStatusText:
    def _emp(self, expiry_iso: str, status: str = "") -> dict:
        return {"Дата окончания": expiry_iso, "Статус уведомлений": status}

    def test_in_progress_status(self):
        emp = self._emp("2030-01-01", status="в процессе")
        assert "В процессе" in employee_status_text(emp)

    def test_no_date_shows_unknown(self):
        emp = self._emp("")
        assert "не указана" in employee_status_text(emp)

    def test_past_date_shows_expired(self):
        emp = self._emp("2000-01-01")
        assert "Просрочена" in employee_status_text(emp)

    def test_far_future_shows_active(self):
        emp = self._emp("2099-01-01")
        assert "Активна" in employee_status_text(emp)

    def test_invalid_date_format(self):
        emp = self._emp("bad-date")
        assert "Некорректная" in employee_status_text(emp)

    def test_expires_today(self):
        today = date.today().strftime("%Y-%m-%d")
        emp = self._emp(today)
        assert "сегодня" in employee_status_text(emp).lower()

    def test_expires_tomorrow(self):
        tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        emp = self._emp(tomorrow)
        assert "завтра" in employee_status_text(emp).lower()

    def test_expires_in_5_days(self):
        soon = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
        emp = self._emp(soon)
        assert "5" in employee_status_text(emp)

    def test_expires_in_7_days(self):
        soon = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
        emp = self._emp(soon)
        assert "7" in employee_status_text(emp)


# ---------------------------------------------------------------------------
# employee_card
# ---------------------------------------------------------------------------

class TestEmployeeCard:
    def _full_emp(self) -> dict:
        return {
            "ФИО": "Иванов Иван Иванович",
            "Телефон": "+79161234567",
            "Должность": "Повар",
            "Дата окончания": "2030-06-15",
            "Chat ID": "123456",
            "Подразделение": "Кухня",
            "В главной группе": "да",
            "В группе подразделения": "да",
            "Статус уведомлений": "",
        }

    def test_contains_fio(self):
        assert "Иванов Иван Иванович" in employee_card(self._full_emp())

    def test_contains_phone(self):
        assert "+79161234567" in employee_card(self._full_emp())

    def test_contains_position(self):
        assert "Повар" in employee_card(self._full_emp())

    def test_contains_subdivision(self):
        assert "Кухня" in employee_card(self._full_emp())

    def test_date_converted_to_display_format(self):
        assert "15-06-2030" in employee_card(self._full_emp())

    def test_missing_fields_show_dash(self):
        emp = {
            "ФИО": "", "Телефон": "", "Должность": "",
            "Дата окончания": "", "Chat ID": "", "Подразделение": "",
            "В главной группе": "", "В группе подразделения": "",
            "Статус уведомлений": "",
        }
        card = employee_card(emp)
        assert "—" in card
