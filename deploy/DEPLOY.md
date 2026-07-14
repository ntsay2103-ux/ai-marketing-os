# AI Marketing OS — Инструкция по деплою

**Сервер:** Ubuntu 24.04 LTS  
**Запуск:** systemd  
**Путь:** `/opt/ai-marketing-os`  
**Пользователь:** `botuser`

---

## Первый деплой

### 1. Подключитесь к серверу

```bash
ssh root@YOUR_SERVER_IP
```

### 2. Замените URL репозитория в setup.sh

Откройте `deploy/setup.sh` и замените строку:
```
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git "$APP_DIR"
```
на реальный URL вашего GitHub-репозитория.

### 3. Загрузите setup.sh на сервер и запустите

```bash
# На сервере — клонируем только для получения скрипта
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git /tmp/ai-marketing-os-setup
sudo bash /tmp/ai-marketing-os-setup/deploy/setup.sh
```

### 4. Заполните секреты

```bash
nano /opt/ai-marketing-os/.env
```

Укажите реальные значения для всех переменных из `.env.example`:
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
OPENROUTER_API_KEY=...
KIE_API_KEY=...
```

### 5. Загрузите фотобиблиотеку

Ваши фотографии из `assets/photos/` нужно загрузить вручную (они не в git):

```bash
# С локальной машины (Windows):
scp -r "C:\Users\uliat\AI-Marketing-OS\assets\photos" root@YOUR_SERVER_IP:/opt/ai-marketing-os/assets/

# Установите правильного владельца:
chown -R botuser:botuser /opt/ai-marketing-os/assets/
```

### 6. Запустите бота

```bash
systemctl start ai-marketing-os
systemctl status ai-marketing-os
```

При первом запуске бот автоматически скачает шрифты Manrope из Google Fonts.

---

## Установка зависимостей (вручную, если нужно)

```bash
cd /opt/ai-marketing-os
sudo -u botuser venv/bin/pip install -r requirements.txt
```

---

## Обновление через git pull

```bash
# 1. Остановить бота
systemctl stop ai-marketing-os

# 2. Обновить код
cd /opt/ai-marketing-os
sudo -u botuser git pull origin main

# 3. Обновить зависимости (если изменился requirements.txt)
sudo -u botuser venv/bin/pip install -r requirements.txt

# 4. Перезапустить
systemctl start ai-marketing-os
systemctl status ai-marketing-os
```

---

## Управление сервисом

```bash
# Запустить
systemctl start ai-marketing-os

# Остановить
systemctl stop ai-marketing-os

# Перезапустить
systemctl restart ai-marketing-os

# Статус
systemctl status ai-marketing-os
```

---

## Просмотр логов

```bash
# Логи в реальном времени
journalctl -u ai-marketing-os -f

# Последние 100 строк
journalctl -u ai-marketing-os -n 100

# Логи за сегодня
journalctl -u ai-marketing-os --since today

# Только ошибки
journalctl -u ai-marketing-os -p err
```

---

## Проверка автозапуска после перезагрузки

Автозапуск включён при установке (`systemctl enable`). Проверка:

```bash
# Убедиться что сервис включён в автозапуск
systemctl is-enabled ai-marketing-os
# Ожидаемый ответ: enabled

# Полная проверка — симулируем перезагрузку
systemctl reboot
# После перезагрузки:
ssh root@YOUR_SERVER_IP
systemctl status ai-marketing-os
# Статус должен быть: active (running)
```

---

## Структура на сервере

```
/opt/ai-marketing-os/
├── engine/              # Код бота (из git)
├── config/              # Дизайн-конфиги (из git)
├── deploy/              # Деплой-файлы (из git)
├── venv/                # Python venv (создаётся при установке)
├── .env                 # Секреты (НЕ в git, создаётся вручную)
├── data/                # Данные кампаний (НЕ в git)
├── sessions/            # Сессии LLM (НЕ в git)
└── assets/
    ├── fonts/           # Скачиваются автоматически при запуске
    ├── photos/          # Загружаются вручную через scp
    └── photos_tips/     # Загружаются вручную через scp
```

---

## Частые проблемы

**Бот не запускается — ошибка шрифтов**  
```bash
# Убедитесь что пакеты шрифтов установлены:
apt list --installed | grep -E "fonts-dejavu|fonts-liberation"
```

**Бот не видит TELEGRAM_BOT_TOKEN**  
```bash
# Проверьте .env:
cat /opt/ai-marketing-os/.env
# Проверьте права:
ls -la /opt/ai-marketing-os/.env  # должно быть -rw------- botuser botuser
```

**Конфликт запущенных процессов**  
```bash
# Только один процесс должен быть активен:
ps aux | grep "engine/run.py"
# Если несколько — убить лишние:
pkill -f "engine/run.py"
systemctl start ai-marketing-os
```
