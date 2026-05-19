from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

COMMANDS_DEFAULT = [
    BotCommand(command="start", description="Регистрация / Главное меню"),
    BotCommand(command="mycard", description="Моя карточка медкнижки"),
    BotCommand(command="whoami", description="Мой профиль и Chat ID"),
    BotCommand(command="request_admin", description="Запросить доступ администратора"),
    BotCommand(command="cancel", description="Отменить текущее действие"),
]

COMMANDS_ADMIN = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="admin_panel", description="Панель администратора"),
    BotCommand(command="status", description="Сводка по медкнижкам"),
    BotCommand(command="list", description="Список истекающих медкнижек"),
    BotCommand(command="expired", description="Список просроченных"),
    BotCommand(command="check", description="Найти сотрудника"),
    BotCommand(command="add", description="Добавить сотрудника"),
    BotCommand(command="broadcast", description="Рассылка сотрудникам"),
    BotCommand(command="run_check", description="Запустить проверку вручную"),
    BotCommand(command="mycard", description="Моя карточка"),
    BotCommand(command="whoami", description="Мой профиль"),
    BotCommand(command="cancel", description="Отменить действие"),
]

COMMANDS_OWNER = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="admin_panel", description="Панель администратора"),
    BotCommand(command="status", description="Сводка по медкнижкам"),
    BotCommand(command="list", description="Список истекающих медкнижек"),
    BotCommand(command="expired", description="Список просроченных"),
    BotCommand(command="check", description="Найти сотрудника"),
    BotCommand(command="add", description="Добавить сотрудника"),
    BotCommand(command="broadcast", description="Рассылка сотрудникам"),
    BotCommand(command="run_check", description="Запустить проверку вручную"),
    BotCommand(command="admins", description="Список администраторов"),
    BotCommand(command="approve_admin", description="Выдать доступ администратора"),
    BotCommand(command="revoke_admin", description="Отозвать доступ"),
    BotCommand(command="mycard", description="Моя карточка"),
    BotCommand(command="whoami", description="Мой профиль"),
    BotCommand(command="cancel", description="Отменить действие"),
]


async def set_user_commands(bot: Bot, chat_id: int, role: str) -> None:
    if role == "owner":
        commands = COMMANDS_OWNER
    elif role == "admin":
        commands = COMMANDS_ADMIN
    else:
        commands = COMMANDS_DEFAULT
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception:
        pass


async def setup_commands(bot: Bot) -> None:
    from google_sheets import get_admin_rows, ADMIN_ROLE_OWNER
    from config import DEVELOPER_CHAT_ID

    await bot.set_my_commands(COMMANDS_DEFAULT, scope=BotCommandScopeDefault())

    if DEVELOPER_CHAT_ID:
        await set_user_commands(bot, DEVELOPER_CHAT_ID, "owner")

    for admin in get_admin_rows(with_row_numbers=False):
        if admin["state"] == "active":
            role = "owner" if admin["role"] == ADMIN_ROLE_OWNER else "admin"
            await set_user_commands(bot, admin["chat_id"], role)
