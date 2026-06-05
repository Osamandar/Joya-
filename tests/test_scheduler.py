"""
Тесты для scheduler.py.

Запуск:
    pytest tests/ -v

Что покрывают тесты:
  - сотрудник с истечением через 7 дней → уведомление сотруднику + список админов
  - сотрудник с истечением через 4 дня → + уведомление в группу подразделения
  - сотрудник с истечением через 2 дня → в главную группу (без уведомления лично)
  - сотрудник просрочен → строка красная, список срочных уведомлений
  - сотрудник в статусе «в процессе» → полностью пропускается
  - сотрудник с истёкшим статусом, но дата ещё не наступила → статус сбрасывается
  - некорректная дата в записи → запись молча пропускается
  - нет сотрудников → сообщений не отправляется
"""

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# Путь импорта относительно корня проекта
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scheduler import daily_check


# ---------------------------------------------------------------------------
# Вспомогательные фикстуры
# ---------------------------------------------------------------------------

def make_employee(
    fio: str = "Иванов И.И.",
    position: str = "Повар",
    days_delta: int = 7,          # +N = через N дней, -N = просрочена N дней назад
    chat_id: str = "111222333",
    subdivision: str = "Кухня",
    in_main: str = "да",
    in_sub: str = "да",
    status: str = "",
    row_number: int = 2,
    today: date | None = None,
) -> dict:
    _today = today or date.today()
    expiry = _today + timedelta(days=days_delta)
    return {
        "ФИО": fio,
        "Должность": position,
        "Дата окончания": expiry.strftime("%Y-%m-%d"),
        "Chat ID": chat_id,
        "Подразделение": subdivision,
        "В главной группе": in_main,
        "В группе подразделения": in_sub,
        "Статус уведомлений": status,
        "row_number": row_number,
    }


@pytest.fixture
def bot():
    b = AsyncMock()
    b.send_message = AsyncMock()
    return b


# ---------------------------------------------------------------------------
# Патчим внешние зависимости одним контекст-менеджером
# ---------------------------------------------------------------------------

BASE_PATCHES = {
    "scheduler.get_all_employees":      [],
    "scheduler.get_notification_admin_ids": [],
    "scheduler.get_sub_groups":         {},
    "scheduler.set_row_red":            MagicMock(),
    "scheduler.set_row_default":        MagicMock(),
    "scheduler.set_employee_status":    MagicMock(),
    "scheduler.clear_employee_status":  MagicMock(),
    "scheduler.MAIN_GROUP_ID":          -1001111111,
    "scheduler.DEVELOPER_CHAT_ID":      None,
}


def run_check(bot, employees, admins, sub_groups=None, main_group_id=-1001111111):
    """Запускает daily_check с заданными данными и возвращает результат."""
    patches = {
        "scheduler.get_all_employees":          employees,
        "scheduler.get_notification_admin_ids": admins,
        "scheduler.get_sub_groups":             sub_groups or {},
        "scheduler.set_row_red":                MagicMock(),
        "scheduler.set_row_default":            MagicMock(),
        "scheduler.set_employee_status":        MagicMock(),
        "scheduler.clear_employee_status":      MagicMock(),
        "scheduler.MAIN_GROUP_ID":              main_group_id,
        "scheduler.DEVELOPER_CHAT_ID":          None,
    }
    with patch.multiple("scheduler", **{
        k.replace("scheduler.", ""): (v if callable(v) or isinstance(v, (list, dict, int, type(None))) else v)
        for k, v in patches.items()
    }):
        # Создаём отдельные MagicMock для функций, остальное передаём как значения
        ctx_managers = []
        for key, val in patches.items():
            module, attr = key.split(".", 1)
            if callable(val) and not isinstance(val, (list, dict)):
                ctx_managers.append(patch(key, val))
            else:
                ctx_managers.append(patch(key, val))

        # Используем patch.multiple с явным разделением
        with patch("scheduler.get_all_employees", return_value=employees), \
             patch("scheduler.get_notification_admin_ids", return_value=admins), \
             patch("scheduler.get_sub_groups", return_value=sub_groups or {}), \
             patch("scheduler.set_row_red") as mock_red, \
             patch("scheduler.set_row_default") as mock_default, \
             patch("scheduler.set_employee_status") as mock_status, \
             patch("scheduler.clear_employee_status") as mock_clear, \
             patch("scheduler.MAIN_GROUP_ID", main_group_id), \
             patch("scheduler.DEVELOPER_CHAT_ID", None):

            asyncio.run(daily_check(bot))
            return {
                "set_row_red": mock_red,
                "set_row_default": mock_default,
                "set_employee_status": mock_status,
                "clear_employee_status": mock_clear,
            }


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

class TestDailyCheckNoEmployees:
    def test_no_messages_sent_when_no_employees(self, bot):
        run_check(bot, employees=[], admins=[999])
        bot.send_message.assert_not_called()


class TestExpiringSoon:
    def test_7_days_notifies_employee_and_admins(self, bot):
        emp = make_employee(days_delta=7, chat_id="111")
        mocks = run_check(bot, employees=[emp], admins=[777])

        calls = bot.send_message.call_args_list
        chat_ids = [c.args[0] for c in calls]

        # Сотрудник должен получить личное уведомление
        assert 111 in chat_ids, "Личное уведомление сотруднику не отправлено"
        # Администратор должен получить список
        assert 777 in chat_ids, "Уведомление администратору не отправлено"
        # Строка не должна окрашиваться
        mocks["set_row_red"].assert_not_called()

    def test_4_days_notifies_employee_admins_and_subgroup(self, bot):
        emp = make_employee(days_delta=4, chat_id="111", subdivision="Кухня")
        mocks = run_check(
            bot,
            employees=[emp],
            admins=[777],
            sub_groups={"Кухня": -1009999},
        )

        chat_ids = [c.args[0] for c in bot.send_message.call_args_list]
        assert 111 in chat_ids,    "Личное уведомление сотруднику не отправлено"
        assert 777 in chat_ids,    "Уведомление администратору не отправлено"
        assert -1009999 in chat_ids, "Уведомление в группу подразделения не отправлено"

    def test_2_days_notifies_admins_and_main_group_only(self, bot):
        emp = make_employee(days_delta=2, chat_id="111", in_main="да")
        run_check(bot, employees=[emp], admins=[777], main_group_id=-1001111)

        chat_ids = [c.args[0] for c in bot.send_message.call_args_list]
        # Лично сотруднику НЕ отправляем за 1-3 дня
        assert 111 not in chat_ids, "Личное уведомление за 2 дня отправлено — не должно"
        assert 777 in chat_ids,    "Уведомление администратору не отправлено"
        assert -1001111 in chat_ids, "Уведомление в главную группу не отправлено"

    def test_no_personal_message_if_no_chat_id(self, bot):
        """Сотрудник без chat_id — личное сообщение не отправляется."""
        emp = make_employee(days_delta=6, chat_id="")
        run_check(bot, employees=[emp], admins=[777])

        chat_ids = [c.args[0] for c in bot.send_message.call_args_list]
        # Только админ, не сотрудник
        assert chat_ids == [777], f"Неожиданные получатели: {chat_ids}"


class TestExpired:
    def test_expired_marks_row_red_and_notifies_admins(self, bot):
        emp = make_employee(days_delta=-3, chat_id="111", status="")
        mocks = run_check(bot, employees=[emp], admins=[777])

        mocks["set_row_red"].assert_called_once_with(2)
        mocks["set_employee_status"].assert_called_once_with(2, "expired")

        chat_ids = [c.args[0] for c in bot.send_message.call_args_list]
        assert 777 in chat_ids, "Срочное уведомление администратору не отправлено"
        # Личное уведомление просроченному сотруднику — не отправляется
        assert 111 not in chat_ids

    def test_already_expired_status_not_doubled(self, bot):
        """Если статус уже 'expired', повторно не красим и не шлём."""
        emp = make_employee(days_delta=-1, status="expired")
        mocks = run_check(bot, employees=[emp], admins=[777])

        mocks["set_row_red"].assert_not_called()
        mocks["set_employee_status"].assert_not_called()
        bot.send_message.assert_not_called()

    def test_was_expired_now_valid_resets_status(self, bot):
        """Статус 'expired', но дата ещё не наступила → сбрасываем."""
        emp = make_employee(days_delta=10, status="expired")
        mocks = run_check(bot, employees=[emp], admins=[777])

        mocks["set_row_default"].assert_called_once_with(2)
        mocks["clear_employee_status"].assert_called_once_with(2)


class TestSkipped:
    def test_in_progress_status_skipped_entirely(self, bot):
        emp = make_employee(days_delta=3, status="в процессе")
        mocks = run_check(bot, employees=[emp], admins=[777])

        bot.send_message.assert_not_called()
        mocks["set_row_red"].assert_not_called()

    def test_invalid_date_skipped_gracefully(self, bot):
        emp = make_employee(days_delta=7)
        emp["Дата окончания"] = "не-дата"
        # Не должно бросать исключение
        run_check(bot, employees=[emp], admins=[777])
        bot.send_message.assert_not_called()

    def test_employee_more_than_7_days_skipped(self, bot):
        emp = make_employee(days_delta=8)
        run_check(bot, employees=[emp], admins=[777])
        bot.send_message.assert_not_called()


class TestMultipleEmployees:
    def test_admin_receives_one_combined_message(self, bot):
        """Несколько сотрудников → одно сводное сообщение администратору."""
        employees = [
            make_employee("Иванов", days_delta=5, chat_id="111", row_number=2),
            make_employee("Петров", days_delta=5, chat_id="222", row_number=3),
        ]
        run_check(bot, employees=employees, admins=[777])

        admin_calls = [c for c in bot.send_message.call_args_list if c.args[0] == 777]
        # Одно сводное сообщение, не по одному на каждого сотрудника
        assert len(admin_calls) == 1, f"Ожидалось 1 сообщение администратору, получили {len(admin_calls)}"
        text = admin_calls[0].args[1]
        assert "Иванов" in text and "Петров" in text, "Оба сотрудника должны быть в одном сообщении"
