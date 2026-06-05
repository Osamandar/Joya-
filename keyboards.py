from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from config import POSITIONS

CONSENT_YES = "✅ Согласен на обработку ПДн"
CONSENT_NO = "❌ Не согласен"

_EDIT_FIELD_BUTTONS = {
    "📅 Дата окончания": "expiry",
    "📱 Телефон": "phone",
    "💼 Должность": "position",
    "🏢 Подразделение": "subdivision",
    "🟡 В процессе": "in_progress",
}


def consent_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CONSENT_YES)], [KeyboardButton(text=CONSENT_NO)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить номер из Telegram", request_contact=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def position_keyboard() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=p)] for p in POSITIONS]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def subdivision_keyboard(names: list[str]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=name)] for name in names]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def edit_field_keyboard() -> ReplyKeyboardMarkup:
    keys = list(_EDIT_FIELD_BUTTONS)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=keys[0]), KeyboardButton(text=keys[1])],
            [KeyboardButton(text=keys[2]), KeyboardButton(text=keys[3])],
            [KeyboardButton(text=keys[4])],
            [KeyboardButton(text="◀️ Назад"), KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def action_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✏️ Редактировать"), KeyboardButton(text="🗑 Удалить")],
            [KeyboardButton(text="◀️ Назад"), KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def yes_no_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Да"), KeyboardButton(text="Нет")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статус"), KeyboardButton(text="📋 Список на 7 дней")],
            [KeyboardButton(text="🚨 Просроченные"), KeyboardButton(text="🔍 Проверить")],
            [KeyboardButton(text="✏️ Редактировать"), KeyboardButton(text="🗑 Удалить")],
            [KeyboardButton(text="▶️ Проверить сейчас"), KeyboardButton(text="❌ Закрыть меню")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def get_owner_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статус"), KeyboardButton(text="📋 Список на 7 дней")],
            [KeyboardButton(text="🚨 Просроченные"), KeyboardButton(text="🔍 Проверить")],
            [KeyboardButton(text="✏️ Редактировать"), KeyboardButton(text="🗑 Удалить")],
            [KeyboardButton(text="▶️ Проверить сейчас"), KeyboardButton(text="👥 Администраторы")],
            [KeyboardButton(text="❌ Закрыть меню")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )
