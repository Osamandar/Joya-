import gspread
import json
import os
import time
from datetime import datetime
from pathlib import Path

# FIX #1: заменили устаревший oauth2client на google-auth
from google.oauth2.service_account import Credentials

# FIX #7: добавили tenacity для автоматического повтора при ошибках API
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from config import (
    SPREADSHEET_NAME, SHEET_EMPLOYEES, SHEET_ADMINS, SHEET_GROUPS,
    COL_FIO, COL_PHONE, COL_POSITION, COL_EXPIRY, COL_CHAT_ID,
    COL_IN_MAIN, COL_IN_SUB, COL_SUBDIVISION, COL_PD_CONSENT, COL_STATUS,
    DEVELOPER_CHAT_ID,
)
import re

GOOGLE_CREDENTIALS_FILE = Path(__file__).with_name("google_credentials.json")
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

EMPLOYEE_STATUS_HEADER = "Статус уведомлений"
ADMIN_HEADERS = [
    "Chat ID",
    "ФИО",
    "Username",
    "Роль",
    "Подразделение",
    "Активен",
    "Кто выдал доступ",
    "Дата выдачи",
    "Дата запроса",
]

# FIX #5: заменили магические числа колонок константами для листа «Админы»
COL_ADMIN_CHAT_ID    = 1
COL_ADMIN_FIO        = 2
COL_ADMIN_USERNAME   = 3
COL_ADMIN_ROLE       = 4
COL_ADMIN_SUBDIV     = 5
COL_ADMIN_ACTIVE     = 6
COL_ADMIN_GRANTED_BY = 7
COL_ADMIN_GRANTED_AT = 8
COL_ADMIN_REQUESTED  = 9

ADMIN_ROLE_OWNER = "owner"
ADMIN_ROLE_ADMIN = "admin"
ADMIN_STATE_ACTIVE = "да"
ADMIN_STATE_PENDING = "заявка"
ADMIN_STATE_INACTIVE = "нет"

_employees_service_column_ready = False
_admin_sheet_ready = False
_client = None
_sheet = None

_CACHE_TTL_EMPLOYEES = 60
_CACHE_TTL_ADMINS = 300
_CACHE_TTL_GROUPS = 600
_cache: dict[str, tuple] = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.time() < expires_at:
        return value
    del _cache[key]
    return None


def _cache_set(key: str, value, ttl: int):
    _cache[key] = (value, time.time() + ttl)


def _cache_clear(*keys: str):
    for key in keys:
        _cache.pop(key, None)


def normalize_phone(phone) -> str:
    """Приводит телефон к виду +7XXXXXXXXXX."""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("7"):
        return f"+{digits}"
    return str(phone).strip()


def _strip_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _today_iso() -> str:
    return datetime.now().date().isoformat()


def _ensure_columns(ws, expected_count: int):
    current_cols = getattr(ws, "col_count", 0) or 0
    if current_cols < expected_count:
        ws.add_cols(expected_count - current_cols)


def _ensure_employee_service_column(ws):
    global _employees_service_column_ready
    if _employees_service_column_ready:
        return
    _ensure_columns(ws, COL_STATUS)
    current = ws.cell(1, COL_STATUS).value
    if _strip_cell(current) != EMPLOYEE_STATUS_HEADER:
        ws.update_cell(1, COL_STATUS, EMPLOYEE_STATUS_HEADER)
    _employees_service_column_ready = True


def _ensure_admin_sheet_structure(ws):
    global _admin_sheet_ready
    if _admin_sheet_ready:
        return
    _ensure_columns(ws, len(ADMIN_HEADERS))
    header_row = ws.row_values(1)
    expected = header_row[:len(ADMIN_HEADERS)]
    if expected != ADMIN_HEADERS:
        ws.update([ADMIN_HEADERS], "A1")
    _admin_sheet_ready = True


def _normalize_admin_role(chat_id: int, raw_role: str) -> str:
    role = _strip_cell(raw_role).lower()
    if role in {ADMIN_ROLE_OWNER, ADMIN_ROLE_ADMIN}:
        return role
    if DEVELOPER_CHAT_ID and chat_id == DEVELOPER_CHAT_ID:
        return ADMIN_ROLE_OWNER
    return ADMIN_ROLE_ADMIN


def _normalize_admin_state(raw_state: str) -> tuple[str, str]:
    value = _strip_cell(raw_state).lower()
    if value in {"yes", "true", "1", "active", ADMIN_STATE_ACTIVE}:
        return "active", ADMIN_STATE_ACTIVE
    if value in {"pending", "request", ADMIN_STATE_PENDING}:
        return "pending", ADMIN_STATE_PENDING
    if value in {"no", "false", "0", "inactive", "revoked", ADMIN_STATE_INACTIVE}:
        return "inactive", ADMIN_STATE_INACTIVE
    return "active", ADMIN_STATE_ACTIVE


def _normalize_admin_record(row_number: int, record: dict) -> dict | None:
    chat_id_raw = _strip_cell(record.get("Chat ID"))
    if not chat_id_raw or not chat_id_raw.lstrip("-").isdigit():
        return None

    chat_id = int(chat_id_raw)
    state, active_value = _normalize_admin_state(record.get("Активен", ""))
    return {
        "row_number": row_number,
        "chat_id": chat_id,
        "fio": _strip_cell(record.get("ФИО")),
        "username": _strip_cell(record.get("Username")).lstrip("@"),
        "role": _normalize_admin_role(chat_id, record.get("Роль", "")),
        "subdivision": _strip_cell(record.get("Подразделение")),
        "state": state,
        "active": active_value,
        "granted_by": _strip_cell(record.get("Кто выдал доступ")),
        "granted_at": _strip_cell(record.get("Дата выдачи")),
        "requested_at": _strip_cell(record.get("Дата запроса")),
    }


# FIX #1 + #7: новая авторизация через google-auth с retry при ошибках API
@retry(
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(4),
    retry=retry_if_exception_type((gspread.exceptions.APIError, ConnectionError, TimeoutError)),
    reraise=True,
)
def get_client():
    global _client
    if _client is None:
        env_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if env_json:
            creds = Credentials.from_service_account_info(
                json.loads(env_json), scopes=SCOPE
            )
        elif GOOGLE_CREDENTIALS_FILE.is_file():
            creds = Credentials.from_service_account_file(
                str(GOOGLE_CREDENTIALS_FILE), scopes=SCOPE
            )
        else:
            raise RuntimeError(
                f"Не найден файл {GOOGLE_CREDENTIALS_FILE.name} "
                "и не задана переменная GOOGLE_CREDENTIALS_JSON."
            )
        _client = gspread.authorize(creds)
    return _client


def get_spreadsheet():
    global _sheet
    if _sheet is None:
        try:
            _sheet = get_client().open(SPREADSHEET_NAME)
        except gspread.SpreadsheetNotFound as exc:
            raise RuntimeError(
                f'Таблица "{SPREADSHEET_NAME}" не найдена или сервисному аккаунту не выдан доступ.'
            ) from exc
    return _sheet


def get_employees_sheet():
    ws = get_spreadsheet().worksheet(SHEET_EMPLOYEES)
    _ensure_employee_service_column(ws)
    return ws


def get_admins_sheet():
    ws = get_spreadsheet().worksheet(SHEET_ADMINS)
    _ensure_admin_sheet_structure(ws)
    return ws


def get_groups_sheet():
    return get_spreadsheet().worksheet(SHEET_GROUPS)


def ensure_google_sheets_ready():
    try:
        get_employees_sheet()
        get_admins_sheet()
        get_groups_sheet()
    except gspread.WorksheetNotFound as exc:
        raise RuntimeError(
            "В Google Таблице не хватает обязательных листов. "
            "Запусти `python3 setup_sheet.py`, чтобы подготовить структуру."
        ) from exc


def find_employee_by_chat_id(chat_id: int):
    """Ищет строку по Chat ID. Возвращает номер строки или None."""
    ws = get_employees_sheet()
    records = ws.get_all_values()[1:]
    for i, row in enumerate(records):
        if len(row) >= COL_CHAT_ID and str(row[COL_CHAT_ID - 1]).strip() == str(chat_id):
            return i + 2
    return None


def find_employee_by_phone(phone: str):
    """Ищет строку по телефону (независимо от Chat ID)."""
    ws = get_employees_sheet()
    records = ws.get_all_values()[1:]
    target = normalize_phone(phone)
    for i, row in enumerate(records):
        if len(row) < COL_PHONE:
            continue
        if normalize_phone(row[COL_PHONE - 1]) == target:
            return i + 2
    return None


def find_employee_by_fio_phone(fio: str, phone: str):
    """Ищет строку сотрудника с пустым Chat ID по ФИО и телефону."""
    ws = get_employees_sheet()
    records = ws.get_all_values()[1:]
    for i, row in enumerate(records):
        if len(row) < COL_PHONE:
            continue
        if (
            row[COL_FIO - 1].strip().lower() == fio.strip().lower()
            and normalize_phone(row[COL_PHONE - 1]) == normalize_phone(phone)
            and (len(row) < COL_CHAT_ID or not row[COL_CHAT_ID - 1].strip())
        ):
            return i + 2
    return None


def update_chat_id(row_number: int, chat_id: int):
    ws = get_employees_sheet()
    ws.update_cell(row_number, COL_CHAT_ID, str(chat_id))
    _cache_clear("employee_rows")


def get_cell(row_number: int, col: int) -> str:
    ws = get_employees_sheet()
    val = ws.cell(row_number, col).value
    return (val or "").strip()


def update_subdivision(row_number: int, subdivision: str):
    ws = get_employees_sheet()
    ws.update_cell(row_number, COL_SUBDIVISION, subdivision)
    _cache_clear("employee_rows")


def update_pd_consent(row_number: int, consent: str):
    ws = get_employees_sheet()
    ws.update_cell(row_number, COL_PD_CONSENT, consent)
    _cache_clear("employee_rows")


def add_employee_row(
    fio: str,
    phone: str,
    position: str,
    chat_id: int | str = "",
    subdivision: str = "",
    in_main: str = "да",
    in_sub: str = "да",
    pd_consent: str = "да",
    expiry: str = "",
):
    """Добавляет нового сотрудника в таблицу."""
    ws = get_employees_sheet()
    row = [
        fio,
        normalize_phone(phone),
        position,
        expiry,
        str(chat_id) if chat_id else "",
        in_main,
        in_sub,
        subdivision,
        pd_consent,
        "",
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")
    _cache_clear("employee_rows")
    return ws.row_count


# FIX #4: заменили 5–6 отдельных update_cell на один batch_update (экономит квоту API)
def complete_employee_registration(
    row_number: int,
    chat_id: int,
    position: str,
    subdivision: str,
    pd_consent: str,
    phone: str | None = None,
):
    """Заполняет данные для существующей строки (добавленной админом без Chat ID)."""
    ws = get_employees_sheet()

    # Получаем текущие значения флагов «в группе» за один запрос
    current_in_main = get_cell(row_number, COL_IN_MAIN)
    current_in_sub  = get_cell(row_number, COL_IN_SUB)

    # Строим список обновлений и выполняем их одним batch_update
    updates = [
        {"range": f"{_col_letter(COL_POSITION)}{row_number}",   "values": [[position]]},
        {"range": f"{_col_letter(COL_CHAT_ID)}{row_number}",    "values": [[str(chat_id)]]},
        {"range": f"{_col_letter(COL_SUBDIVISION)}{row_number}", "values": [[subdivision]]},
        {"range": f"{_col_letter(COL_PD_CONSENT)}{row_number}", "values": [[pd_consent]]},
    ]
    if phone:
        updates.append(
            {"range": f"{_col_letter(COL_PHONE)}{row_number}", "values": [[normalize_phone(phone)]]}
        )
    if not current_in_main:
        updates.append(
            {"range": f"{_col_letter(COL_IN_MAIN)}{row_number}", "values": [["да"]]}
        )
    if not current_in_sub:
        updates.append(
            {"range": f"{_col_letter(COL_IN_SUB)}{row_number}", "values": [["да"]]}
        )

    ws.batch_update(updates, value_input_option="USER_ENTERED")
    _cache_clear("employee_rows")


def _col_letter(col: int) -> str:
    """Преобразует номер колонки (1-based) в букву/буквы A, B, …, Z, AA, AB, …"""
    result = ""
    while col > 0:
        col, remainder = divmod(col - 1, 26)
        result = chr(65 + remainder) + result
    return result


def get_subdivision_names():
    """Список названий подразделений из листа «Группы»."""
    return list(get_sub_groups().keys())


def _get_raw_employees() -> list[dict]:
    """Fetches all employee rows with row_number from Sheets, using TTL cache."""
    cached = _cache_get("employee_rows")
    if cached is not None:
        return cached
    ws = get_employees_sheet()
    records = ws.get_all_records(numericise_ignore=["all"])
    result = []
    for row_number, rec in enumerate(records, start=2):
        employee = {key: _strip_cell(value) for key, value in rec.items()}
        employee["row_number"] = row_number
        result.append(employee)
    _cache_set("employee_rows", result, _CACHE_TTL_EMPLOYEES)
    return result


def get_employee_rows(
    include_without_chat: bool = False,
    with_row_numbers: bool = False,
    require_expiry: bool = False,
):
    """Возвращает список словарей сотрудников из листа «Сотрудники»."""
    employees = []
    for employee in _get_raw_employees():
        if require_expiry and not employee.get("Дата окончания"):
            continue
        if not include_without_chat and not employee.get("Chat ID"):
            continue
        if with_row_numbers:
            employees.append(employee)
        else:
            employees.append({k: v for k, v in employee.items() if k != "row_number"})
    return employees


def get_all_employees(include_without_chat: bool = False, with_row_numbers: bool = False):
    """Возвращает сотрудников с заполненной датой окончания."""
    return get_employee_rows(
        include_without_chat=include_without_chat,
        with_row_numbers=with_row_numbers,
        require_expiry=True,
    )


def search_employees(query: str, include_without_chat: bool = True):
    """Поиск сотрудника по части ФИО или телефону."""
    query_text = query.strip().lower()
    query_digits = re.sub(r"\D", "", query)
    if not query_text and not query_digits:
        return []

    matches = []
    for employee in get_employee_rows(include_without_chat=include_without_chat, with_row_numbers=True):
        fio = (employee.get("ФИО") or "").lower()
        phone = employee.get("Телефон") or ""
        phone_digits = re.sub(r"\D", "", phone)
        if query_text and query_text in fio:
            matches.append(employee)
            continue
        if query_digits and query_digits in phone_digits:
            matches.append(employee)
    return matches


def _get_raw_admins() -> list[dict]:
    """Fetches all admin rows with row_number from Sheets, using TTL cache."""
    cached = _cache_get("admin_rows")
    if cached is not None:
        return cached
    ws = get_admins_sheet()
    records = ws.get_all_records(numericise_ignore=["all"])
    admins = []
    for row_number, rec in enumerate(records, start=2):
        admin = _normalize_admin_record(row_number, rec)
        if not admin:
            continue
        admins.append(admin)
    _cache_set("admin_rows", admins, _CACHE_TTL_ADMINS)
    return admins


def get_admin_rows(with_row_numbers: bool = True):
    """Возвращает все записи листа «Админы» в нормализованном виде."""
    if with_row_numbers:
        return list(_get_raw_admins())
    return [{k: v for k, v in admin.items() if k != "row_number"} for admin in _get_raw_admins()]


def get_admin_record(chat_id: int) -> dict | None:
    for admin in get_admin_rows(with_row_numbers=True):
        if admin["chat_id"] == chat_id:
            return admin
    return None


def has_admin_access(chat_id: int) -> bool:
    if DEVELOPER_CHAT_ID and chat_id == DEVELOPER_CHAT_ID:
        return True
    admin = get_admin_record(chat_id)
    return bool(admin and admin["state"] == "active")


def has_owner_access(chat_id: int) -> bool:
    if DEVELOPER_CHAT_ID and chat_id == DEVELOPER_CHAT_ID:
        return True
    admin = get_admin_record(chat_id)
    return bool(admin and admin["state"] == "active" and admin["role"] == ADMIN_ROLE_OWNER)


def get_admins():
    return [admin["chat_id"] for admin in get_admin_rows(with_row_numbers=False) if admin["state"] == "active"]


def get_owner_admin_ids(include_developer: bool = True):
    ids = []
    if include_developer and DEVELOPER_CHAT_ID:
        ids.append(DEVELOPER_CHAT_ID)
    ids.extend(
        admin["chat_id"]
        for admin in get_admin_rows(with_row_numbers=False)
        if admin["state"] == "active" and admin["role"] == ADMIN_ROLE_OWNER
    )
    return list(dict.fromkeys(ids))


def get_notification_admin_ids():
    ids = []
    if DEVELOPER_CHAT_ID:
        ids.append(DEVELOPER_CHAT_ID)
    ids.extend(
        admin["chat_id"]
        for admin in get_admin_rows(with_row_numbers=False)
        if admin["state"] == "active" and admin["role"] == ADMIN_ROLE_ADMIN
    )
    return list(dict.fromkeys(ids))


def _append_admin_row(
    chat_id: int,
    fio: str = "",
    username: str = "",
    role: str = ADMIN_ROLE_ADMIN,
    subdivision: str = "",
    active: str = ADMIN_STATE_ACTIVE,
    granted_by: str = "",
    granted_at: str = "",
    requested_at: str = "",
):
    ws = get_admins_sheet()
    ws.append_row(
        [
            str(chat_id),
            fio,
            username.lstrip("@"),
            role,
            subdivision,
            active,
            granted_by,
            granted_at,
            requested_at,
        ],
        value_input_option="USER_ENTERED",
    )
    _cache_clear("admin_rows")


# FIX #5: используем именованные константы вместо магических чисел
def _update_admin_field(row_number: int, col: int, value: str):
    ws = get_admins_sheet()
    ws.update_cell(row_number, col, value)
    _cache_clear("admin_rows")


def create_or_update_admin_request(chat_id: int, fio: str, username: str, subdivision: str = "") -> str:
    """Создаёт или обновляет заявку на админ-доступ."""
    admin = get_admin_record(chat_id)
    request_date = _today_iso()
    username_clean = username.lstrip("@")

    if admin:
        row_number = admin["row_number"]
        _update_admin_field(row_number, COL_ADMIN_FIO,      fio)
        _update_admin_field(row_number, COL_ADMIN_USERNAME,  username_clean)
        if subdivision:
            _update_admin_field(row_number, COL_ADMIN_SUBDIV, subdivision)

        if admin["state"] == "active":
            return "active"
        if admin["state"] == "pending":
            _update_admin_field(row_number, COL_ADMIN_REQUESTED, request_date)
            return "pending"

        _update_admin_field(row_number, COL_ADMIN_ACTIVE,   ADMIN_STATE_PENDING)
        _update_admin_field(row_number, COL_ADMIN_REQUESTED, request_date)
        return "requested"

    _append_admin_row(
        chat_id=chat_id,
        fio=fio,
        username=username_clean,
        subdivision=subdivision,
        active=ADMIN_STATE_PENDING,
        requested_at=request_date,
    )
    return "requested"


def approve_admin_access(
    chat_id: int,
    granted_by: str,
    role: str = ADMIN_ROLE_ADMIN,
    subdivision: str = "",
) -> dict:
    """Выдаёт или подтверждает админ-доступ."""
    if role not in {ADMIN_ROLE_OWNER, ADMIN_ROLE_ADMIN}:
        raise ValueError(f"Unsupported admin role: {role}")

    admin = get_admin_record(chat_id)
    granted_at = _today_iso()
    if admin:
        row_number = admin["row_number"]
        _update_admin_field(row_number, COL_ADMIN_ROLE,       role)
        _update_admin_field(row_number, COL_ADMIN_ACTIVE,     ADMIN_STATE_ACTIVE)
        _update_admin_field(row_number, COL_ADMIN_GRANTED_BY, granted_by)
        _update_admin_field(row_number, COL_ADMIN_GRANTED_AT, granted_at)
        if subdivision:
            _update_admin_field(row_number, COL_ADMIN_SUBDIV, subdivision)
    else:
        _append_admin_row(
            chat_id=chat_id,
            role=role,
            subdivision=subdivision,
            active=ADMIN_STATE_ACTIVE,
            granted_by=granted_by,
            granted_at=granted_at,
        )

    return get_admin_record(chat_id) or {}


def revoke_admin_access(chat_id: int) -> dict | None:
    """Отключает админ-доступ для пользователя."""
    admin = get_admin_record(chat_id)
    if not admin:
        return None
    _update_admin_field(admin["row_number"], COL_ADMIN_ACTIVE, ADMIN_STATE_INACTIVE)
    return get_admin_record(chat_id)


def get_sub_groups():
    """Словарь {название подразделения: ID группы Telegram}."""
    cached = _cache_get("group_rows")
    if cached is not None:
        return cached
    ws = get_groups_sheet()
    records = ws.get_all_records()
    groups = {}
    for rec in records:
        group_id = rec.get("ID группы подразделения") or rec.get("ID группы")
        if not group_id:
            continue
        name = (
            rec.get("Подразделение")
            or rec.get("Должность")
            or ""
        ).strip()
        if name and str(group_id).strip().lstrip("-").isdigit():
            groups[name] = int(group_id)
    _cache_set("group_rows", groups, _CACHE_TTL_GROUPS)
    return groups


def set_row_red(row_number: int):
    """Закрашивает строку красным (просрочена)."""
    ws = get_employees_sheet()
    ws.format(f"{row_number}:{row_number}", {
        "backgroundColor": {"red": 1, "green": 0.8, "blue": 0.8}
    })


def set_row_yellow(row_number: int):
    """Закрашивает строку жёлтым (в процессе переоформления)."""
    ws = get_employees_sheet()
    ws.format(f"{row_number}:{row_number}", {
        "backgroundColor": {"red": 1, "green": 0.95, "blue": 0.4}
    })


def set_row_default(row_number: int):
    """Сбрасывает цвет строки на белый."""
    ws = get_employees_sheet()
    ws.format(f"{row_number}:{row_number}", {
        "backgroundColor": {"red": 1, "green": 1, "blue": 1}
    })


def get_employee_status(row_number: int) -> str:
    return get_cell(row_number, COL_STATUS)


def set_employee_status(row_number: int, status: str):
    ws = get_employees_sheet()
    ws.update_cell(row_number, COL_STATUS, status.strip())
    _cache_clear("employee_rows")


def clear_employee_status(row_number: int):
    set_employee_status(row_number, "")


def update_employee_cell(row_number: int, col: int, value: str):
    ws = get_employees_sheet()
    ws.update_cell(row_number, col, value)
    _cache_clear("employee_rows")


def delete_employee_row(row_number: int):
    ws = get_employees_sheet()
    ws.delete_rows(row_number)
    _cache_clear("employee_rows")


def get_employee_row_dict(row_number: int) -> dict:
    """Returns all employee fields using a single API call."""
    ws = get_employees_sheet()
    values = ws.row_values(row_number)
    while len(values) < COL_STATUS:
        values.append("")
    return {
        "ФИО":                   values[COL_FIO - 1].strip(),
        "Телефон":               values[COL_PHONE - 1].strip(),
        "Должность":             values[COL_POSITION - 1].strip(),
        "Дата окончания":        values[COL_EXPIRY - 1].strip(),
        "Chat ID":               values[COL_CHAT_ID - 1].strip(),
        "В главной группе":      values[COL_IN_MAIN - 1].strip(),
        "В группе подразделения": values[COL_IN_SUB - 1].strip(),
        "Подразделение":         values[COL_SUBDIVISION - 1].strip(),
        "Статус уведомлений":    values[COL_STATUS - 1].strip(),
    }
