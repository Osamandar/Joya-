import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, SCHEDULE_HOUR, SCHEDULE_MINUTE
from google_sheets import ensure_google_sheets_ready
from handlers import router
from scheduler import daily_check
from commands import setup_commands

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _build_storage():
    """
    Возвращает RedisStorage если задана переменная REDIS_URL,
    иначе — MemoryStorage (FSM не переживёт перезапуск бота).

    На Railway:
      1. Добавь сервис Redis (New → Database → Redis)
      2. Railway автоматически пробросит переменную REDIS_URL в твой сервис бота
    """
    redis_url = os.getenv("REDIS_URL") or os.getenv("REDIS_PRIVATE_URL")
    if redis_url:
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            storage = RedisStorage.from_url(redis_url)
            logger.info("FSM: используем RedisStorage (%s)", redis_url.split("@")[-1])
            return storage
        except Exception as exc:
            logger.warning(
                "Не удалось подключиться к Redis (%s), переключаемся на MemoryStorage: %s",
                redis_url, exc,
            )
    else:
        logger.warning(
            "REDIS_URL не задан — используем MemoryStorage. "
            "FSM-состояния будут сброшены при перезапуске бота."
        )
    return MemoryStorage()


async def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "Нет BOT_TOKEN. Создай файл .env в папке проекта (см. .env.example)."
        )

    try:
        ensure_google_sheets_ready()
    except Exception as exc:
        raise SystemExit(f"Ошибка подключения к Google Sheets: {exc}") from exc

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=_build_storage())
    dp.include_router(router)

    await setup_commands(bot)

    # timezone="Europe/Moscow" гарантирует, что SCHEDULE_HOUR=9 — это 9:00 МСК,
    # независимо от часового пояса сервера Railway (UTC).
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        daily_check,
        "cron",
        hour=SCHEDULE_HOUR,
        minute=SCHEDULE_MINUTE,
        args=[bot],
        misfire_grace_time=300,
    )
    scheduler.start()

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
