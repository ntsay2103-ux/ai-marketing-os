"""
Единственный модуль, который знает о файловой системе.
Все остальные модули читают и пишут данные только через Store.
Для перехода на SQLite — заменить этот файл, остальное не трогать.
"""

import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent


class Store:
    def __init__(self, project: str):
        self.project = project
        self.project_dir = BASE_DIR / "data" / project
        self.sessions_dir = BASE_DIR / "sessions"

        if not self.project_dir.exists():
            raise FileNotFoundError(
                f"Проект '{project}' не найден: {self.project_dir}"
            )

    # --- Чтение ---

    def load_profile(self) -> str:
        return self._read(self.project_dir / "profile.md")

    def load_insights(self) -> str:
        return self._read(self.project_dir / "insights.md")

    def load_idea_bank(self) -> str:
        return self._read(self.project_dir / "idea_bank.md")

    def load_results_log(self) -> str:
        return self._read(self.project_dir / "results_log.md")

    # --- Запись ---

    def save_session(self, content: str, session_type: str = "session") -> Path:
        self.sessions_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        path = self.sessions_dir / f"{timestamp}_{self.project}_{session_type}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def save_json(self, data: dict, session_type: str = "session") -> Path:
        self.sessions_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        path = self.sessions_dir / f"{timestamp}_{self.project}_{session_type}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def save_raw_error(self, raw: str, reason: str) -> Path:
        self.sessions_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = self.sessions_dir / f"{timestamp}_{self.project}_parse_error.txt"
        header = f"# ОШИБКА ПАРСИНГА JSON\n# Причина: {reason}\n\n"
        path.write_text(header + raw, encoding="utf-8")
        return path

    def load_candidates(self) -> str:
        return self._read(self.project_dir / "candidate_ideas.md")

    def load_candidate_ideas(self) -> list[dict]:
        path = self.project_dir / "candidate_ideas.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def append_candidates(self, ideas: list[dict], funnel_stage: str, session_date: str) -> Path:
        # Сохраняем в JSON (источник истины для Stage 5)
        existing = self.load_candidate_ideas()
        for idea in ideas:
            existing.append({
                "session_date": session_date,
                "funnel_stage": funnel_stage,
                **idea,
            })
        json_path = self.project_dir / "candidate_ideas.json"
        json_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

        # Обновляем Markdown (для чтения человеком)
        self._rebuild_candidates_md(existing)
        return self.project_dir / "candidate_ideas.md"

    def save_candidate_ideas(self, ideas: list[dict]) -> None:
        path = self.project_dir / "candidate_ideas.json"
        path.write_text(json.dumps(ideas, ensure_ascii=False, indent=2), encoding="utf-8")
        self._rebuild_candidates_md(ideas)

    def _rebuild_candidates_md(self, ideas: list[dict]) -> None:
        path = self.project_dir / "candidate_ideas.md"
        header = (
            "# Кандидаты на публикацию — ЧистоПодКлюч\n\n"
            "> Идеи, найденные системой в ходе research-сессий.\n"
            "> Статус по умолчанию: ожидает решения.\n"
            "> Одобренные идеи переносятся в idea_bank.md вручную.\n\n"
            "---\n"
        )
        if not ideas:
            path.write_text(header + "\n_Идей пока нет. Файл заполнится после первой research-сессии._\n", encoding="utf-8")
            return

        # Группируем по сессиям
        sessions: dict[str, list[dict]] = {}
        for idea in ideas:
            key = f"{idea.get('session_date', '—')} · Аудитория: {idea.get('funnel_stage', '—')}"
            sessions.setdefault(key, []).append(idea)

        blocks = []
        for session_key, session_ideas in sessions.items():
            blocks.append(f"\n## Сессия {session_key}\n")
            for idea in session_ideas:
                potential = idea.get("potential", "—")
                blocks.append(f"### {idea.get('title', '—')}  `[{potential}]`\n")
                blocks.append(f"- **Источник:** {idea.get('source', '—')}")
                blocks.append(f"- **Триггер:** {idea.get('trigger', '—')}")
                blocks.append(f"- **Потенциал:** {potential} — {idea.get('potential_rationale', '—')}")
                blocks.append(f"- **Адаптация:** {idea.get('adaptation', '—')}")
                blocks.append(f"- **Статус:** ожидает решения\n")

        path.write_text(header + "\n".join(blocks), encoding="utf-8")

    def load_bank_ideas(self) -> list[dict]:
        path = self.project_dir / "idea_bank.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def save_bank_ideas(self, ideas: list[dict]) -> None:
        path = self.project_dir / "idea_bank.json"
        path.write_text(json.dumps(ideas, ensure_ascii=False, indent=2), encoding="utf-8")
        self._rebuild_bank_md(ideas)

    # --- Tips Bank ---

    def load_tips_bank(self) -> list[dict]:
        path = self.project_dir / "tips_bank.json"
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def save_tips_bank(self, tips: list[dict]) -> None:
        path = self.project_dir / "tips_bank.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tips, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def get_pending_tips(self) -> list[dict]:
        return [t for t in self.load_tips_bank() if t.get("status") == "pending_review"]

    def update_tip_status(self, tip_title: str, status: str) -> None:
        tips = self.load_tips_bank()
        for t in tips:
            if t.get("title") == tip_title:
                t["status"] = status
                break
        self.save_tips_bank(tips)

    def approve_idea(self, idea: dict) -> None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        entry = {
            **idea,
            "status": "approved_waiting_content",
            "approved_date": date_str,
        }
        ideas = self.load_bank_ideas()
        ideas.append(entry)
        self.save_bank_ideas(ideas)

    def next_for_create(self) -> dict | None:
        for idea in self.load_bank_ideas():
            if idea.get("status") == "approved_waiting_content":
                return idea
        return None

    def mark_content_created(self, idea: dict) -> None:
        ideas = self.load_bank_ideas()
        for entry in ideas:
            if entry.get("title") == idea.get("title") and entry.get("status") == "approved_waiting_content":
                entry["status"] = "content_created"
                entry["content_date"] = datetime.now().strftime("%Y-%m-%d")
                break
        self.save_bank_ideas(ideas)

    def next_for_publish(self) -> dict | None:
        for idea in self.load_bank_ideas():
            if idea.get("status") == "content_created":
                return idea
        return None

    def mark_published(self, idea: dict) -> None:
        ideas = self.load_bank_ideas()
        for entry in ideas:
            if entry.get("title") == idea.get("title") and entry.get("status") == "content_created":
                entry["status"] = "published"
                entry["published_date"] = datetime.now().strftime("%Y-%m-%d")
                break
        self.save_bank_ideas(ideas)

    def _rebuild_bank_md(self, ideas: list[dict]) -> None:
        path = self.project_dir / "idea_bank.md"
        header = (
            "# Банк идей — ЧистоПодКлюч\n\n"
            "> Содержит только одобренные пользователем идеи.\n"
            "> Пополняется автоматически через команду `python engine/run.py review`.\n"
            "> Система учитывает этот файл при генерации новых идей, чтобы избегать повторов.\n\n"
            "---\n"
        )
        waiting   = [i for i in ideas if i.get("status") == "approved_waiting_content"]
        created   = [i for i in ideas if i.get("status") == "content_created"]
        published = [i for i in ideas if i.get("status") == "published"]

        def _idea_block(idea: dict, fields: list[tuple[str, str]]) -> list[str]:
            potential = idea.get("potential", "—")
            rows = [f"### {idea.get('title', '—')}  `[{potential}]`"]
            for label, key in fields:
                rows.append(f"- **{label}:** {idea.get(key, '—')}")
            rows.append("")
            return rows

        lines = ["\n## Ожидают создания контента\n"]
        if waiting:
            for idea in waiting:
                lines += _idea_block(idea, [("Адаптация", "adaptation"), ("Одобрена", "approved_date")])
        else:
            lines.append("_Нет идей, ожидающих создания контента._\n")

        lines += ["---\n", "## Контент создан, ожидает публикации\n"]
        if created:
            for idea in created:
                lines += _idea_block(idea, [("Адаптация", "adaptation"), ("Одобрена", "approved_date"), ("Контент создан", "content_date")])
        else:
            lines.append("_Пока нет._\n")

        lines += ["---\n", "## Опубликовано\n"]
        if published:
            for idea in published:
                lines += _idea_block(idea, [("Адаптация", "adaptation"), ("Контент создан", "content_date"), ("Опубликовано", "published_date")])
        else:
            lines.append("_Пока нет._\n")

        path.write_text(header + "\n".join(lines), encoding="utf-8")

    # --- Campaign Specification ---

    def campaigns_dir(self) -> Path:
        d = self.project_dir / "campaigns"
        d.mkdir(exist_ok=True)
        return d

    # приватный псевдоним для обратной совместимости внутри класса
    def _campaigns_dir(self) -> Path:
        return self.campaigns_dir()

    def save_campaign_spec(self, spec: dict, md_content: str) -> Path:
        """Сохраняет Campaign Specification: JSON (источник истины) + MD (для чтения)."""
        d = self._campaigns_dir()
        spec_id = spec["id"]
        json_path = d / f"{spec_id}.json"
        md_path = d / f"{spec_id}.md"
        json_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(md_content, encoding="utf-8")
        return json_path

    def load_campaign_specs(self) -> list[dict]:
        """Возвращает все Campaign Specifications, отсортированные по ID (по времени)."""
        d = self.project_dir / "campaigns"
        if not d.exists():
            return []
        return [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(d.glob("camp_*.json"))
        ]

    def next_spec_for_create(self) -> dict | None:
        """Возвращает первый Campaign Specification с pending-платформой."""
        for spec in self.load_campaign_specs():
            if spec.get("status") == "approved":
                for platform in spec.get("platforms", []):
                    if platform.get("content_status") == "pending":
                        return spec
        return None

    def mark_spec_content_created(self, spec_id: str, content_file: str) -> None:
        """Обновляет статус первой pending-платформы в spec на created."""
        d = self.project_dir / "campaigns"
        json_path = d / f"{spec_id}.json"
        if not json_path.exists():
            return
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        date_str = datetime.now().strftime("%Y-%m-%d")
        for platform in spec.get("platforms", []):
            if platform.get("content_status") == "pending":
                platform["content_status"] = "created"
                platform["content_file"] = str(content_file)
                platform["content_created_at"] = date_str
                break
        pending_left = any(p.get("content_status") == "pending" for p in spec.get("platforms", []))
        if not pending_left:
            spec["status"] = "ready_for_publication"
        json_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    def next_spec_for_publish(self) -> dict | None:
        """Возвращает первый Campaign Specification, готовый к публикации."""
        for spec in self.load_campaign_specs():
            if spec.get("status") == "ready_for_publication":
                return spec
        return None

    def get_published_specs(self) -> list[dict]:
        """Возвращает Campaign Specifications со статусом 'published'."""
        return [s for s in self.load_campaign_specs() if s.get("status") == "published"]

    def save_results_to_spec(self, spec_id: str, results: dict) -> None:
        """
        Сохраняет результаты кампании в Campaign Specification.
        Переводит кампанию в статус 'results_collected' — готова к Insights.
        """
        d = self.project_dir / "campaigns"
        json_path = d / f"{spec_id}.json"
        if not json_path.exists():
            return
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        spec["results"] = {
            **results,
            "collected_at": datetime.now().strftime("%Y-%m-%d"),
        }
        spec["status"] = "results_collected"
        json_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    def mark_spec_platform_published(
        self,
        spec_id: str,
        platform: str,
        published_at: str,
        url: str | None = None,
    ) -> None:
        """
        Фиксирует публикацию платформы в Campaign Specification.
        Если все платформы опубликованы — переводит кампанию в статус 'published'.
        """
        d = self.project_dir / "campaigns"
        json_path = d / f"{spec_id}.json"
        if not json_path.exists():
            return
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        for p in spec.get("platforms", []):
            if p.get("platform") == platform:
                p["content_status"] = "published"
                p["published_at"] = published_at
                p["published_url"] = url
                break
        all_published = all(
            p.get("content_status") == "published"
            for p in spec.get("platforms", [])
        )
        if all_published:
            spec["status"] = "published"
            spec["published_at"] = published_at
        json_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_spec_content_data(self, spec_id: str, content_data: dict) -> None:
        """Сохраняет JSON-данные сгенерированного контента в Campaign Specification."""
        json_path = self.campaigns_dir() / f"{spec_id}.json"
        if not json_path.exists():
            return
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        spec["content_data"] = content_data
        json_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_spec_content_data(self, spec_id: str) -> dict | None:
        """Загружает JSON-данные контента из Campaign Specification."""
        json_path = self.campaigns_dir() / f"{spec_id}.json"
        if not json_path.exists():
            return None
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        return spec.get("content_data")

    def get_latest_content_spec(self) -> dict | None:
        """Возвращает последний spec со статусом ready_for_publication или content_data."""
        for spec in reversed(self.load_campaign_specs()):
            if spec.get("status") in ("ready_for_publication", "published") and spec.get("content_data"):
                return spec
        return None

    def save_instagram_format(self, spec_id: str, fmt: str) -> None:
        """Сохраняет выбранный формат Instagram (carousel / reels) в Campaign Specification."""
        json_path = self.campaigns_dir() / f"{spec_id}.json"
        if not json_path.exists():
            return
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        spec["instagram_format"] = fmt
        json_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_pub_statuses(self, spec_id: str, statuses: dict) -> None:
        """Сохраняет словарь статусов публикации по платформам."""
        json_path = self.campaigns_dir() / f"{spec_id}.json"
        if not json_path.exists():
            return
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        spec["pub_statuses"] = statuses
        json_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_pub_status(self, spec_id: str, platform: str, status: str) -> None:
        """Обновляет статус публикации для одной платформы."""
        json_path = self.campaigns_dir() / f"{spec_id}.json"
        if not json_path.exists():
            return
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        spec.setdefault("pub_statuses", {})[platform] = status
        json_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_pub_statuses(self, spec_id: str) -> dict:
        """Возвращает словарь статусов публикации по платформам."""
        json_path = self.campaigns_dir() / f"{spec_id}.json"
        if not json_path.exists():
            return {}
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        return spec.get("pub_statuses", {})

    def save_carousel_images(self, spec_id: str, slide_images: dict) -> None:
        """Сохраняет пути к изображениям слайдов: {slide_num_str: path_str}."""
        json_path = self.campaigns_dir() / f"{spec_id}.json"
        if not json_path.exists():
            return
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        spec["carousel_images"] = slide_images
        json_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_carousel_images(self, spec_id: str) -> dict:
        """Возвращает пути к изображениям слайдов: {slide_num_str: path_str}."""
        json_path = self.campaigns_dir() / f"{spec_id}.json"
        if not json_path.exists():
            return {}
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        return spec.get("carousel_images", {})

    def save_spec_image_path(self, spec_id: str, image_path: str) -> None:
        """Сохраняет путь к изображению в Campaign Specification."""
        json_path = self.campaigns_dir() / f"{spec_id}.json"
        if not json_path.exists():
            return
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        spec["image_path"] = image_path
        json_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    def update_insights(self, content: str) -> None:
        path = self.project_dir / "insights.md"
        path.write_text(content, encoding="utf-8")

    def append_to_results_log(self, row: str) -> None:
        path = self.project_dir / "results_log.md"
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n{row}")

    # --- Внутреннее ---

    def _read(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
