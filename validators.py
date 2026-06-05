import re
from datetime import datetime

from google_sheets import (
    ADMIN_ROLE_ADMIN,
    ADMIN_ROLE_OWNER,
    clear_employee_status,
    get_subdivision_names,
    search_employees,
    set_employee_status,
    set_row_default,
    set_row_red,
    update_employee_cell,
)
from config import (
    COL_EXPIRY,
    COL_IN_MAIN,
    COL_IN_SUB,
    COL_PHONE,
    COL_POSITION,
    COL_SUBDIVISION,
    POSITION_TO_SUBDIVISION,
)

EDIT_FIELD_ALIASES = {
    "date": "expiry",
    "expiry": "expiry",
    "дата": "expiry",
    "срок": "expiry",
    "position": "position",
    "должность": "position",
    "subdivision": "subdivision",
    "подразделение": "subdivision",
    "main": "main_group",
    "главная": "main_group",
    "maingroup": "main_group",
    "sub": "sub_group",
    "subgroup": "sub_group",
    "группа": "sub_group",
    "подгруппа": "sub_group",
    "phone": "phone",
    "телефон": "phone",
}
ADMIN_ROLE_ALIASES = {
    "admin": ADMIN_ROLE_ADMIN,
    "админ": ADMIN_ROLE_ADMIN,
    "owner": ADMIN_ROLE_OWNER,
    "владелец": ADMIN_ROLE_OWNER,
}


def normalize_phone_input(phone_raw: str) -> str | None:
    phone_clean = re.sub(r"[^\d+]", "", phone_raw.strip())
    if re.match(r"^\+7\d{10}$", phone_clean):
        return phone_clean
    digits = re.sub(r"\D", "", phone_raw)
    if len(digits) == 11 and digits.startswith("8"):
        return f"+7{digits[1:]}"
    if len(digits) == 11 and digits.startswith("7"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+7{digits}"
    return None


def parse_yes_no(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized in {"да", "yes", "y", "1", "true"}:
        return "да"
    if normalized in {"нет", "no", "n", "0", "false"}:
        return "нет"
    return None


def resolve_edit_field(raw_field: str) -> str | None:
    return EDIT_FIELD_ALIASES.get(raw_field.strip().lower())


def resolve_admin_role(raw_role: str) -> str | None:
    return ADMIN_ROLE_ALIASES.get(raw_role.strip().lower())


def resolve_subdivision(position: str) -> str | None:
    sub = POSITION_TO_SUBDIVISION.get(position, "").strip()
    active = get_subdivision_names()
    if sub and sub in active:
        return sub
    return None


def find_single_employee(query: str) -> tuple[dict | None, str | None]:
    matches = search_employees(query)
    if not matches:
        return None, "Сотрудник не найден."
    if len(matches) > 1:
        lines = [
            f"{emp['ФИО']} | {emp.get('Телефон') or '—'} | {emp.get('Должность') or '—'}"
            for emp in matches[:10]
        ]
        suffix = ""
        if len(matches) > 10:
            suffix = f"\n\nНайдено {len(matches)} совпадений. Уточните ФИО или номер телефона."
        return None, "Найдено несколько сотрудников:\n" + "\n".join(lines) + suffix
    return matches[0], None


def _apply_employee_edit(row_number: int, field: str, new_value: str) -> str | None:
    """Applies one field update. Returns an error string if validation fails, None on success."""
    if field == "expiry":
        try:
            expiry_date = datetime.strptime(new_value, "%d-%m-%Y").date()
        except ValueError:
            return "Дата должна быть в формате ДД-ММ-ГГГГ, например 31-12-2026."
        update_employee_cell(row_number, COL_EXPIRY, expiry_date.isoformat())
        delta = (expiry_date - datetime.now().date()).days
        if delta <= 0:
            set_row_red(row_number)
            set_employee_status(row_number, "expired")
        else:
            set_row_default(row_number)
            clear_employee_status(row_number)
    elif field == "phone":
        normalized_phone = normalize_phone_input(new_value)
        if not normalized_phone:
            return "Телефон должен быть в формате +79161234567."
        update_employee_cell(row_number, COL_PHONE, normalized_phone)
    elif field == "position":
        update_employee_cell(row_number, COL_POSITION, new_value)
        auto_sub = resolve_subdivision(new_value)
        if auto_sub:
            update_employee_cell(row_number, COL_SUBDIVISION, auto_sub)
    elif field == "subdivision":
        subdivisions = get_subdivision_names()
        normalized_sub = "" if new_value in {"-", "пусто", "none"} else new_value
        if not subdivisions and normalized_sub:
            return "Не удалось загрузить список подразделений. Повторите попытку."
        if subdivisions and normalized_sub and normalized_sub not in subdivisions:
            names_text = "\n".join(f"• {name}" for name in subdivisions)
            return f"Такого подразделения нет в листе «Группы». Доступные варианты:\n\n{names_text}"
        update_employee_cell(row_number, COL_SUBDIVISION, normalized_sub)
    elif field == "main_group":
        parsed = parse_yes_no(new_value)
        if not parsed:
            return "Для поля «главная» используй значение да или нет."
        update_employee_cell(row_number, COL_IN_MAIN, parsed)
    elif field == "sub_group":
        parsed = parse_yes_no(new_value)
        if not parsed:
            return "Для поля «подгруппа» используй значение да или нет."
        update_employee_cell(row_number, COL_IN_SUB, parsed)
    return None
