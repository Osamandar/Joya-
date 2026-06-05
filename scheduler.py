import asyncio
import logging

# FIX #3: используем zoneinfo для корректного московского времени
from zoneinfo import ZoneInfo
from datetime import datetime

from aiogram import Bot
from config import MAIN_GROUP_ID, DEVELOPER_CHAT_ID
from google_sheets import (
    clear_employee_status,
    get_all_employees,
    get_notification_admin_ids,
    get_sub_groups,
    set_employee_status,
    set_row_default,
    set_row_red,
)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _fmt_date(iso_str: str) -> str:
    """Converts YYYY-MM-DD (storage) → DD-MM-YYYY (display)."""
    try:
        return datetime.strptime(iso_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    except (ValueError, TypeError):
        return iso_str


def _parse_chat_id(raw_value: str) -> int | None:
    value = (raw_value or "").strip()
    if value and value.lstrip("-").isdigit():
        return int(value)
    return None


def _is_yes(raw_value: str) -> bool:
    return (raw_value or "").strip().lower() == "да"


def _expired_line(fio: str, position: str, expiry_str: str, delta: int) -> str:
    if delta == 0:
        return f"{fio} ({position}) - истекает сегодня ({expiry_str})"
    return f"{fio} ({position}) - просрочена на {abs(delta)} дн. (дата: {expiry_str})"


async def daily_check(bot: Bot):
    # FIX #3: now() с явным московским часовым поясом
    today = datetime.now(MOSCOW_TZ).date()

    employees = get_all_employees(include_without_chat=True, with_row_numbers=True)
    admins = get_notification_admin_ids()
    sub_groups = get_sub_groups()

    admins_list = set()
    admins_urgent_list = set()
    main_group_list = []
    sub_group_msgs = {}

    for emp in employees:
        try:
            expiry = datetime.strptime(emp["Дата окончания"], "%Y-%m-%d").date()
        except ValueError:
            continue

        delta = (expiry - today).days
        row_number = emp["row_number"]
        status = (emp.get("Статус уведомлений") or "").strip().lower()
        fio = emp["ФИО"]
        pos = emp["Должность"]
        expiry_str = _fmt_date(emp["Дата окончания"])

        if status == "в процессе":
            continue

        if delta <= 0:
            if status != "expired":
                set_row_red(row_number)
                set_employee_status(row_number, "expired")
                admins_urgent_list.add(_expired_line(fio, pos, expiry_str, delta))
            continue

        if status == "expired":
            set_row_default(row_number)
            clear_employee_status(row_number)

        if delta > 7:
            continue

        in_main = _is_yes(emp.get("В главной группе", ""))
        in_sub = _is_yes(emp.get("В группе подразделения", ""))
        chat_id = _parse_chat_id(emp.get("Chat ID", ""))

        if delta in (7, 6):
            if chat_id:
                msg = (
                    f"Уважаемый(ая) {fio}, срок вашей медицинской книжки "
                    f"истекает {expiry_str} (через {delta} дн.)."
                )
                await send_safe(bot, chat_id, msg)
                await asyncio.sleep(0.15)
            admins_list.add(f"{fio} ({pos}) - {expiry_str}")

        elif delta in (5, 4):
            if chat_id:
                msg = (
                    f"Уважаемый(ая) {fio}, срок вашей медицинской книжки "
                    f"истекает {expiry_str} (через {delta} дн.)."
                )
                await send_safe(bot, chat_id, msg)
                await asyncio.sleep(0.15)
            admins_list.add(f"{fio} ({pos}) - {expiry_str}")
            sub_name = (emp.get("Подразделение") or "").strip()
            if in_sub and sub_name and sub_name in sub_groups:
                group_id = sub_groups[sub_name]
                sub_group_msgs.setdefault(group_id, []).append(f"{fio} - {expiry_str}")

        elif delta in (3, 2, 1):
            admins_list.add(f"{fio} ({pos}) - {expiry_str}")
            if in_main:
                main_group_list.append(f"{fio} ({pos}) - {expiry_str}")

    if admins_urgent_list:
        text = "Срок медкнижки истёк или истекает сегодня:\n" + "\n".join(sorted(admins_urgent_list))
        for admin_id in admins:
            await send_safe(bot, admin_id, text)
            await asyncio.sleep(0.15)

    if admins_list:
        text = "Напоминание о медкнижках:\n" + "\n".join(sorted(admins_list))
        for admin_id in admins:
            await send_safe(bot, admin_id, text)
            await asyncio.sleep(0.15)

    for group_id, items in sub_group_msgs.items():
        text = (
            "Внимание! Срок медкнижек истекает через 4-5 дней у следующих сотрудников:\n"
            + "\n".join(items)
        )
        await send_safe(bot, group_id, text)
        await asyncio.sleep(0.15)

    if main_group_list and MAIN_GROUP_ID:
        text = (
            "Внимание! Через 1-3 дня истекают медкнижки у сотрудников:\n"
            + "\n".join(main_group_list)
        )
        await send_safe(bot, MAIN_GROUP_ID, text)
        await asyncio.sleep(0.15)


async def send_safe(bot: Bot, chat_id: int | None, text: str):
    if not chat_id:
        return
    try:
        await bot.send_message(chat_id, text)
    except Exception as e:
        logging.error(f"Failed to send to {chat_id}: {e}")
        if DEVELOPER_CHAT_ID:
            try:
                await bot.send_message(DEVELOPER_CHAT_ID, f"Ошибка отправки в {chat_id}: {e}")
            except Exception:
                pass
