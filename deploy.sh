#!/usr/bin/env bash
set -e

# Настройте эти переменные перед запуском
PROJECT_DIR="/path/to/your/project"
USER_NAME="your_user"
SERVICE_FILE="joki-bot.service"

cd "$PROJECT_DIR"

# Создать виртуальное окружение, если ещё нет
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# Установить зависимости
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Проверить конфигурацию
if [ ! -f ".env" ]; then
  echo ".env не найден. Создайте его на основе .env.example" >&2
  exit 1
fi
if [ ! -f "google_credentials.json" ]; then
  echo "google_credentials.json не найден. Положите файл в корень проекта." >&2
  exit 1
fi

# Установить systemd-сервис
sudo cp "$PROJECT_DIR/$SERVICE_FILE" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now joki-bot.service
sudo systemctl status --no-pager joki-bot.service
