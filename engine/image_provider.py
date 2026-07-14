"""
Минимальный модуль для генерации изображений через Kie.ai Image API.

Использование:
  from engine.image_provider import generate_image
  url = generate_image("уютная кухня, утренний свет, чистота")

Требует KIE_API_KEY в .env.
Документация: https://docs.kie.ai/4o-image-api/quickstart
"""

import json
import logging
import os
import time

import requests
import yaml
from dotenv import load_dotenv
from pathlib import Path

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")

logger = logging.getLogger(__name__)

_BASE_URL   = "https://api.kie.ai/api/v1"
_STATUS_URL = f"{_BASE_URL}/jobs/recordInfo"

_POLL_INTERVAL = 5    # секунды между проверками
_POLL_TIMEOUT  = 300  # максимальное время ожидания в секундах


def _image_config() -> dict:
    with open(_ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("generation", {}).get("image", {})


def _api_key() -> str:
    key = os.getenv("KIE_API_KEY", "")
    if not key:
        raise EnvironmentError("KIE_API_KEY не найден в .env")
    return key


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


def _submit(prompt: str, size: str | None = None) -> str:
    """Отправляет задание на генерацию. Возвращает taskId."""
    cfg = _image_config()
    endpoint = cfg.get("endpoint", "gpt4o-image")
    generate_url = f"{_BASE_URL}/{endpoint}/generate"
    if size is None:
        size = cfg.get("default_size", "1:1")

    payload = {
        "prompt": prompt,
        "size": size,
        "nVariants": 1,
    }
    resp = requests.post(generate_url, headers=_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != 200:
        raise RuntimeError(f"Kie.ai ошибка при создании задания: {data}")

    task_id = data["data"]["taskId"]
    logger.info(f"[Kie.ai] задание создано: {task_id}")
    return task_id


def _poll(task_id: str) -> str:
    """Ждёт завершения задания и возвращает URL изображения."""
    deadline = time.time() + _POLL_TIMEOUT

    while time.time() < deadline:
        resp = requests.get(
            _STATUS_URL,
            headers=_headers(),
            params={"taskId": task_id},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        state = data.get("state", "")

        logger.info(f"[Kie.ai] taskId={task_id}  state={state}  progress={data.get('progress', 0)}%")

        if state == "success":
            result = json.loads(data["resultJson"])
            urls = result.get("resultUrls", [])
            if not urls:
                raise RuntimeError("Kie.ai вернул success, но resultUrls пуст")
            return urls[0]

        if state == "fail":
            raise RuntimeError(f"Kie.ai: задание завершилось с ошибкой: {data.get('failMsg', '—')}")

        time.sleep(_POLL_INTERVAL)

    raise TimeoutError(f"Kie.ai: задание {task_id} не завершилось за {_POLL_TIMEOUT}с")


def generate_images_parallel(prompts: list[str], size: str) -> list[str | Exception]:
    """
    Генерирует несколько изображений параллельно.
    Возвращает список той же длины, что prompts:
      - str  — URL готового изображения
      - Exception — ошибка для этого слайда
    Успешные не теряются при сбое отдельных.
    """
    from concurrent.futures import ThreadPoolExecutor

    def _gen(prompt: str) -> str | Exception:
        try:
            return generate_image(prompt, size)
        except Exception as exc:
            return exc

    with ThreadPoolExecutor(max_workers=len(prompts)) as executor:
        return list(executor.map(_gen, prompts))


def generate_image(prompt: str, size: str | None = None) -> str:
    """
    Генерирует изображение по текстовому промпту через Kie.ai.

    prompt — описание изображения
    size   — соотношение сторон: "1:1" | "3:2" | "2:3" (None = из config.yaml)

    Возвращает URL готового изображения.
    """
    logger.info(f"[Kie.ai] генерация изображения | size={size} | prompt={prompt[:60]}...")
    task_id = _submit(prompt, size)
    url = _poll(task_id)
    logger.info(f"[Kie.ai] готово: {url}")
    return url


def download_image(url: str, dest_path: Path) -> Path:
    """
    Скачивает изображение по URL и сохраняет его в dest_path.
    Возвращает путь к сохранённому файлу.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=60, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"[Kie.ai] изображение сохранено: {dest_path}")
    return dest_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

    test_prompt = (
        "Уютная чистая кухня, утренний мягкий свет из окна, "
        "на столе чашка кофе, минимализм, фотореализм"
    )
    print(f"Промпт: {test_prompt}\n")
    image_url = generate_image(test_prompt)
    print(f"\nURL изображения:\n{image_url}")
