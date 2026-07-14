#!/bin/bash
# setup.sh — первичная установка AI Marketing OS на Ubuntu 24.04
# Запускать один раз от root: sudo bash deploy/setup.sh

set -e

APP_DIR="/opt/ai-marketing-os"
APP_USER="botuser"
SERVICE_NAME="ai-marketing-os"
REPO_URL="https://github.com/ntsay2103-ux/ai-marketing-os.git"

echo "=== AI Marketing OS: первичная установка ==="

# 1. Системные зависимости
echo "[1/7] Устанавливаю системные пакеты..."
apt-get update -q
apt-get install -y -q \
    python3.12 python3.12-venv python3-pip \
    git \
    fonts-dejavu fonts-liberation \
    libwebp-dev libjpeg-turbo8-dev libpng-dev

# 2. Системный пользователь без shell
echo "[2/7] Создаю пользователя $APP_USER..."
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
    echo "    Пользователь $APP_USER создан"
else
    echo "    Пользователь $APP_USER уже существует"
fi

# 3. Клонирование репозитория
echo "[3/7] Клонирую репозиторий в $APP_DIR..."
# Если директория есть, но engine/ отсутствует — предыдущий clone был неполным, удаляем
if [ -d "$APP_DIR" ] && [ ! -d "$APP_DIR/engine" ]; then
    echo "    Неполная директория — удаляю и клонирую заново"
    rm -rf "$APP_DIR"
fi

if [ ! -d "$APP_DIR" ]; then
    env -i HOME=/root \
        GIT_TERMINAL_PROMPT=0 \
        GIT_ASKPASS=/bin/echo \
        PATH=/usr/bin:/bin \
        git clone "$REPO_URL" "$APP_DIR"
else
    echo "    Репозиторий уже клонирован, пропускаю"
fi

chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

# 4. Python venv + зависимости
echo "[4/7] Создаю виртуальное окружение..."
sudo -u "$APP_USER" python3.12 -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# 5. .env файл
echo "[5/7] Настройка .env..."
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    chown "$APP_USER":"$APP_USER" "$APP_DIR/.env"
    echo ""
    echo "    ⚠️  ВАЖНО: заполните секреты в $APP_DIR/.env"
    echo "    nano $APP_DIR/.env"
    echo ""
else
    echo "    .env уже существует, пропускаю"
fi

# 6. Директории данных
echo "[6/7] Создаю рабочие директории..."
sudo -u "$APP_USER" mkdir -p \
    "$APP_DIR/data/cleaning" \
    "$APP_DIR/assets/fonts" \
    "$APP_DIR/assets/photos" \
    "$APP_DIR/assets/photos_tips" \
    "$APP_DIR/sessions"

# 7. systemd сервис
echo "[7/7] Устанавливаю systemd сервис..."
cp "$APP_DIR/deploy/ai-marketing-os.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo ""
echo "=== Установка завершена ==="
echo ""
echo "Следующие шаги:"
echo "  1. Заполните секреты:  nano $APP_DIR/.env"
echo "  2. Запустите бота:     systemctl start $SERVICE_NAME"
echo "  3. Проверьте статус:   systemctl status $SERVICE_NAME"
echo "  4. Смотрите логи:      journalctl -u $SERVICE_NAME -f"
