import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import BOT_TOKEN, SCHEDULE_HOUR, SCHEDULE_MINUTE
from google_sheets import ensure_google_sheets_ready
from handlers import router
from scheduler import daily_check

logging.basicConfig(level=logging.INFO)

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
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    scheduler = AsyncIOScheduler()
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
