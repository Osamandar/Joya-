#!/usr/bin/env python3
"""
Настройка Google Таблицы для бота медкнижек.

Перед запуском:
  1. google_credentials.json в этой папке
  2. Таблица расшарена на email из JSON (редактор)
  3. Имя таблицы в config.py (SPREADSHEET_NAME) совпадает с Google

Примеры:
  python setup_sheet.py
  python setup_sheet.py --list
  python setup_sheet.py --sample
  python setup_sheet.py --add-admin 123456789
  python setup_sheet.py --add-employee "Иванов Иван" +79161234567 Повар 2026-12-31
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials

from config import (
    SPREADSHEET_NAME,
    SHEET_ADMINS,
    SHEET_EMPLOYEES,
    SHEET_GROUPS,
)

CREDENTIALS_FILE = Path(__file__).parent / "google_credentials.json"
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

HEADERS_EMPLOYEES = [
    "ФИО",
    "Телефон",
    "Должность",
    "Дата окончания",
    "Chat ID",
    "В главной группе",
    "В группе подразделения",
    "Подразделение",
    "Согласие ПДн",
    "Статус уведомлений",
]
HEADERS_ADMINS = [
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
HEADERS_GROUPS = ["Подразделение", "ID группы подразделения"]

# Подразделения в порядке должностей (группа 1 — главная, только в .env → MAIN_GROUP_ID)
SUBDIVISIONS = [
    "Администраторы",
    "БМ",
    "Касса",
    "Бар",
    "Официанты",
    "Кухня",
    "Операторы",
    "Клининг",
    "Техники",
]

SHEET_TITLES = {SHEET_EMPLOYEES, SHEET_ADMINS, SHEET_GROUPS}


def get_client():
    if not CREDENTIALS_FILE.is_file():
        print(f"Не найден файл: {CREDENTIALS_FILE}")
        print("Скачай JSON ключ сервисного аккаунта из Google Cloud и положи сюда.")
        sys.exit(1)
    creds = ServiceAccountCredentials.from_json_keyfile_name(str(CREDENTIALS_FILE), SCOPE)
    return gspread.authorize(creds)


def open_spreadsheet(client):
    try:
        return client.open(SPREADSHEET_NAME)
    except gspread.SpreadsheetNotFound:
        print(f'Таблица «{SPREADSHEET_NAME}» не найдена или нет доступа.')
        print("Проверь:")
        print("  — имя таблицы в config.py (SPREADSHEET_NAME)")
        print("  — доступ для сервисного аккаунта (Поделиться → email из JSON)")
        print("\nДоступные таблицы (запусти: python setup_sheet.py --list):")
        list_spreadsheets(client)
        sys.exit(1)


def list_spreadsheets(client):
    for i, sh in enumerate(client.openall(), 1):
        print(f"  {i}. {sh.title}")


def get_or_create_worksheet(spreadsheet, title, cols=10):
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=500, cols=cols)


def ensure_header(worksheet, headers):
    if worksheet.col_count < len(headers):
        worksheet.add_cols(len(headers) - worksheet.col_count)
    worksheet.update([headers], "A1")
    worksheet.format(
        "1:1",
        {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 0.98},
        },
    )


def remove_empty_default_sheets(spreadsheet):
    for ws in spreadsheet.worksheets():
        if ws.title in SHEET_TITLES:
            continue
        if ws.title not in ("Sheet1", "Лист1", "Sheet 1"):
            continue
        values = ws.get_all_values()
        is_empty = not values or all(not cell.strip() for row in values for cell in row)
        if is_empty and len(spreadsheet.worksheets()) > 1:
            spreadsheet.del_worksheet(ws)
            print(f"  Удалён пустой лист: {ws.title}")


def setup_structure(spreadsheet):
    print(f"Настраиваю таблицу: {spreadsheet.title}")

    ws_emp = get_or_create_worksheet(spreadsheet, SHEET_EMPLOYEES, cols=len(HEADERS_EMPLOYEES))
    ws_adm = get_or_create_worksheet(spreadsheet, SHEET_ADMINS, cols=len(HEADERS_ADMINS))
    ws_grp = get_or_create_worksheet(spreadsheet, SHEET_GROUPS, cols=len(HEADERS_GROUPS))

    ensure_header(ws_emp, HEADERS_EMPLOYEES)
    ensure_header(ws_adm, HEADERS_ADMINS)
    ensure_header(ws_grp, HEADERS_GROUPS)

    remove_empty_default_sheets(spreadsheet)

    print("  Лист «Сотрудники» — заголовки готовы")
    print("  Лист «Админы» — заголовки готовы")
    print("  Лист «Группы» — заголовки готовы")


def add_admin(spreadsheet, chat_id: int, role: str = "admin"):
    ws = spreadsheet.worksheet(SHEET_ADMINS)
    ids = [x.strip() for x in ws.col_values(1)[1:] if x.strip()]
    if str(chat_id) in ids:
        print(f"  Админ {chat_id} уже есть в таблице")
        return
    ws.append_row(
        [str(chat_id), "", "", role, "", "да", "setup_sheet.py", datetime.now().date().isoformat(), ""],
        value_input_option="USER_ENTERED",
    )
    print(f"  Добавлен админ: {chat_id} ({role})")


def add_employee(
    spreadsheet, fio, phone, position, expiry, in_main="да", in_sub="нет", subdivision=""
):
    ws = spreadsheet.worksheet(SHEET_EMPLOYEES)
    row = [fio, phone, position, expiry, "", in_main, in_sub, subdivision, "", ""]
    ws.append_row(row, value_input_option="USER_ENTERED")
    print(f"  Добавлен сотрудник: {fio} ({expiry})")


def init_groups(spreadsheet):
    """Заполняет лист «Группы» названиями подразделений (ID вписываешь вручную)."""
    ws = spreadsheet.worksheet(SHEET_GROUPS)
    ensure_header(ws, HEADERS_GROUPS)
    existing = {r.get("Подразделение", "").strip() for r in ws.get_all_records()}
    added = 0
    for name in SUBDIVISIONS:
        if name in existing:
            continue
        ws.append_row([name, ""], value_input_option="USER_ENTERED")
        added += 1
    print(f"  Лист «Группы»: добавлено {added} подразделений (всего в списке: {len(SUBDIVISIONS)})")
    print("  Впиши ID Telegram-группы в столбец B для каждой строки.")


def add_sample_row(spreadsheet):
    expiry = (datetime.now().date() + timedelta(days=7)).isoformat()
    add_employee(
        spreadsheet,
        fio="Тестов Тест Тестович",
        phone="+79990000000",
        position="Пример должности",
        expiry=expiry,
        in_main="да",
        in_sub="нет",
    )
    print("  (Тестовая строка — удали или измени в таблице после проверки бота)")


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Настройка Google Таблицы для бота медкнижек")
    parser.add_argument("--list", action="store_true", help="Показать все доступные таблицы")
    parser.add_argument(
        "--init-groups",
        action="store_true",
        help="Добавить в лист «Группы» все подразделения (Официанты, Кухня, …)",
    )
    parser.add_argument("--sample", action="store_true", help="Добавить тестового сотрудника (дата +7 дней)")
    parser.add_argument("--add-admin", type=int, metavar="CHAT_ID", help="Добавить Telegram ID админа")
    parser.add_argument(
        "--add-employee",
        nargs=4,
        metavar=("ФИО", "ТЕЛЕФОН", "ДОЛЖНОСТЬ", "ДАТА"),
        help='Добавить сотрудника, дата в формате ГГГГ-ММ-ДД',
    )
    args = parser.parse_args()

    client = get_client()

    if args.list:
        print("Таблицы, доступные сервисному аккаунту:")
        list_spreadsheets(client)
        return

    spreadsheet = open_spreadsheet(client)
    setup_structure(spreadsheet)

    dev_id = os.getenv("DEVELOPER_CHAT_ID")
    if dev_id and dev_id.isdigit():
        add_admin(spreadsheet, int(dev_id), role="owner")
        print(f"  (DEVELOPER_CHAT_ID из .env: {dev_id})")

    if args.add_admin:
        add_admin(spreadsheet, args.add_admin)

    if args.add_employee:
        fio, phone, position, expiry = args.add_employee
        add_employee(spreadsheet, fio, phone, position, expiry)

    if args.init_groups:
        init_groups(spreadsheet)

    if args.sample:
        add_sample_row(spreadsheet)

    print("\nГотово. Открой таблицу в браузере — листы и заголовки на месте.")
    print("Дальше: python main.py → в боте /start с ФИО и телефоном из таблицы.")


if __name__ == "__main__":
    main()
