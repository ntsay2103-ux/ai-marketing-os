#!/usr/bin/env python3
"""
Диагностический скрипт OpenRouter.
Запуск: python3 diag_openrouter.py
Не является частью проекта — удалить после диагностики.
"""
import os
import json
import sys

# --- загружаем .env вручную (без python-dotenv) ---
env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.getenv("OPENROUTER_API_KEY", "")
if not API_KEY:
    print("ERROR: OPENROUTER_API_KEY не найден в .env")
    sys.exit(1)

BASE_URL = "https://openrouter.ai/api/v1"
REFERER  = "https://github.com/ntsay2103-ux/ai-marketing-os"
APP_NAME = "AI Marketing OS"

# маскируем ключ: показываем первые 8 символов
key_preview = API_KEY[:8] + "..." + API_KEY[-4:]

HEADERS = {
    "Authorization":  f"Bearer {API_KEY}",
    "HTTP-Referer":   REFERER,
    "X-Title":        APP_NAME,
    "Content-Type":   "application/json",
}

def print_headers_safe(h: dict):
    for k, v in h.items():
        if k.lower() == "authorization":
            print(f"  {k}: Bearer {key_preview}")
        else:
            print(f"  {k}: {v}")

def divider(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

try:
    import requests
except ImportError:
    print("ERROR: пакет requests не установлен. Установите: pip install requests")
    sys.exit(1)

# ── TEST 1: GET /api/v1/key ──────────────────────────────────
divider("TEST 1: GET /api/v1/key")
url = f"{BASE_URL}/key"
print(f"URL: {url}")
print("Request headers (sent):")
print_headers_safe(HEADERS)

try:
    r = requests.get(url, headers=HEADERS, timeout=15)
    print(f"\nHTTP status: {r.status_code}")
    print("Response body:")
    try:
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(r.text[:2000])
except Exception as e:
    print(f"Exception: {e}")

# ── TEST 2: chat completion, бесплатная модель ───────────────
divider("TEST 2: POST /chat/completions — бесплатная модель")
FREE_MODEL = "meta-llama/llama-3.2-3b-instruct:free"
url = f"{BASE_URL}/chat/completions"
payload = {
    "model": FREE_MODEL,
    "messages": [{"role": "user", "content": "Say: OK"}],
    "max_tokens": 10,
}
print(f"URL: {url}")
print(f"Model: {FREE_MODEL}")
print("Request headers (sent):")
print_headers_safe(HEADERS)
print(f"Body: {json.dumps(payload, ensure_ascii=False)}")

try:
    r = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    print(f"\nHTTP status: {r.status_code}")
    print("Response body:")
    try:
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(r.text[:2000])
except Exception as e:
    print(f"Exception: {e}")

# ── TEST 3: то же через OpenAI SDK ──────────────────────────
divider("TEST 3: OpenAI SDK — бесплатная модель")
try:
    from openai import OpenAI
    client = OpenAI(
        api_key=API_KEY,
        base_url=BASE_URL,
        default_headers={
            "HTTP-Referer": REFERER,
            "X-Title": APP_NAME,
        },
    )
    print(f"Model: {FREE_MODEL}")
    resp = client.chat.completions.create(
        model=FREE_MODEL,
        messages=[{"role": "user", "content": "Say: OK"}],
        max_tokens=10,
    )
    print(f"Result: {resp.choices[0].message.content!r}")
    print(f"Stop reason: {resp.choices[0].finish_reason}")
except Exception as e:
    print(f"Exception ({type(e).__name__}): {e}")

print("\n" + "=" * 60)
print("  Диагностика завершена")
print("=" * 60)
