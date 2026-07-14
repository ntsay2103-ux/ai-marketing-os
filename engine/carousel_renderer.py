"""
Carousel Renderer — локальный рендер Instagram-каруселей на Pillow.
Kie.ai для каруселей не используется.

Два шаблона (авто-определение):
  Template 1 — светлый минималистичный (основной, ~80%)
  Template 2 — первый слайд с крупной цифрой (~20%)

Шрифт: Manrope (assets/fonts/) → система (Arial) → PIL default.
Скачать Manrope: https://fonts.google.com/specimen/Manrope → "Download family"
"""

import json
import logging
import re
import random
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

_ROOT        = Path(__file__).parent.parent
_DESIGN_FILE = _ROOT / "config" / "carousel_design.json"

# ─────────────────────────────────────────────────────────────
# FONTS
# ─────────────────────────────────────────────────────────────

_FONT_CACHE: dict[tuple, ImageFont.FreeTypeFont] = {}

_MANROPE_URLS = {
    "Manrope-ExtraBold.ttf": "https://github.com/googlefonts/manrope/raw/main/fonts/ttf/Manrope-ExtraBold.ttf",
    "Manrope-SemiBold.ttf":  "https://github.com/googlefonts/manrope/raw/main/fonts/ttf/Manrope-SemiBold.ttf",
    "Manrope-Regular.ttf":   "https://github.com/googlefonts/manrope/raw/main/fonts/ttf/Manrope-Regular.ttf",
}


def ensure_fonts() -> None:
    """Скачивает Manrope в assets/fonts/ если отсутствует."""
    font_dir = _ROOT / "assets" / "fonts"
    font_dir.mkdir(parents=True, exist_ok=True)
    for name, url in _MANROPE_URLS.items():
        dest = font_dir / name
        if not dest.exists():
            try:
                logger.info(f"[Renderer] Загружаю шрифт {name}...")
                urllib.request.urlretrieve(url, dest)
                logger.info(f"[Renderer] {name} загружен")
            except Exception as e:
                logger.warning(f"[Renderer] Не удалось загрузить {name}: {e}")


def _load_design() -> dict:
    with open(_DESIGN_FILE, encoding="utf-8") as f:
        return json.load(f)


def _hex(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _get_font(cfg: dict, variant: str, size: int) -> ImageFont.FreeTypeFont:
    key = (variant, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    paths: list[str] = list(cfg["fonts"].get(variant, []))
    paths += cfg["fonts"]["_fallback"]

    for raw in paths:
        path = str(_ROOT / raw) if not Path(raw).is_absolute() else raw
        try:
            f = ImageFont.truetype(path, size)
            _FONT_CACHE[key] = f
            return f
        except (IOError, OSError):
            continue

    logger.warning(f"[Renderer] Шрифт '{variant}' не найден (size={size}), PIL default")
    f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


# ─────────────────────────────────────────────────────────────
# ТЕКСТОВЫЕ УТИЛИТЫ
# ─────────────────────────────────────────────────────────────

def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int, draw: ImageDraw.Draw) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for word in words:
        test = (cur + " " + word).strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def _line_h(font: ImageFont.FreeTypeFont, draw: ImageDraw.Draw, gap: int) -> int:
    return draw.textbbox((0, 0), "Ащ", font=font)[3] + gap


def _fit(
    text: str, draw: ImageDraw.Draw, cfg: dict, variant: str,
    size_max: int, size_min: int, max_w: int, max_h: int,
) -> tuple[list[str], ImageFont.FreeTypeFont, int]:
    """Подбирает максимальный размер шрифта, при котором текст вписывается."""
    gap = cfg["layout"]["line_gap"]
    for size in range(size_max, size_min - 1, -2):
        f = _get_font(cfg, variant, size)
        lines = _wrap(text, f, max_w, draw)
        lh = _line_h(f, draw, gap)
        if len(lines) * lh <= max_h:
            return lines, f, lh
    f = _get_font(cfg, variant, size_min)
    lines = _wrap(text, f, max_w, draw)
    lh = _line_h(f, draw, gap)
    return lines, f, lh


def _split_hook(text: str) -> tuple[str, str, str]:
    """
    Делит текст первого слайда на три части:
    - headline (тёмный, очень крупный)
    - green_sub (зелёный, крупный)
    - support (серый, маленький)
    Приоритет: делим по натуральным разделителям.
    """
    # Сначала ищем длинное тире или запятую
    for sep in [" — ", "—", "–", ","]:
        if sep in text:
            idx = text.index(sep)
            head = text[:idx].strip()
            rest = text[idx + len(sep):].strip()
            # Если rest длинный — делим ещё раз на green+support
            for sep2 in [".", "!", "?"]:
                if sep2 in rest:
                    idx2 = rest.index(sep2)
                    green = rest[:idx2 + 1].strip()
                    support = rest[idx2 + 1:].strip()
                    return head, green, support
            return head, rest, ""

    # По умолчанию: первые 40% слов = headline, остальные = green
    words = text.split()
    mid = max(2, len(words) * 2 // 5)
    return " ".join(words[:mid]), " ".join(words[mid:]), ""


def _split_body(text: str) -> tuple[str, str]:
    """Делит текст внутренних слайдов на headline + body."""
    # По первой точке/восклицанию/вопросу
    m = re.search(r'(?<=[А-ЯЁа-яёA-Za-z\d])[.!?](?:\s|$)', text)
    if m and m.start() > 12:
        return text[:m.start() + 1].strip(), text[m.start() + 1:].strip()
    # По тире
    if " — " in text:
        idx = text.index(" — ")
        return text[:idx].strip(), text[idx + 3:].strip()
    # По середине
    words = text.split()
    if len(words) <= 7:
        return text, ""
    mid = max(4, len(words) * 2 // 5)
    return " ".join(words[:mid]), " ".join(words[mid:])


# ─────────────────────────────────────────────────────────────
# РИСОВАЛЬНЫЕ УТИЛИТЫ
# ─────────────────────────────────────────────────────────────

def _sparkle(draw: ImageDraw.Draw, cx: int, cy: int, r: int, color: tuple) -> None:
    """4-лучевая звёздочка."""
    s = r
    q = max(s // 4, 2)
    pts = [
        (cx, cy - s), (cx + q, cy - q),
        (cx + s, cy), (cx + q, cy + q),
        (cx, cy + s), (cx - q, cy + q),
        (cx - s, cy), (cx - q, cy - q),
    ]
    draw.polygon(pts, fill=color)


def _house_icon(draw: ImageDraw.Draw, x: int, y: int, sz: int, color: tuple, bg: tuple) -> None:
    """Простая иконка домика."""
    # Крыша (треугольник)
    draw.polygon([(x + sz // 2, y), (x, y + sz // 2), (x + sz, y + sz // 2)], fill=color)
    # Стены
    draw.rectangle([x + sz // 8, y + sz // 2, x + sz - sz // 8, y + sz], fill=color)
    # Дверь
    dw, dh = sz // 6, sz // 4
    dx = x + sz // 2 - dw // 2
    draw.rectangle([dx, y + sz - dh, dx + dw, y + sz], fill=bg)


def _logo(draw: ImageDraw.Draw, x: int, y: int, cfg: dict) -> None:
    """Иконка + название бренда."""
    sz   = cfg["sizes"]["logo_icon"]
    col  = _hex(cfg["colors"]["accent"])
    bg   = _hex(cfg["colors"]["bg"])
    _house_icon(draw, x, y, sz, col, bg)
    font = _get_font(cfg, "semibold", cfg["sizes"]["logo_text"])
    draw.text((x + sz + 10, y + (sz - cfg["sizes"]["logo_text"]) // 2),
              cfg["brand"]["name"], font=font, fill=_hex(cfg["colors"]["text_primary"]))


def _indicator(draw: ImageDraw.Draw, cx: int, cy: int, num: int, total: int, cfg: dict) -> None:
    """Кружок «1/4» — правый нижний угол первого слайда."""
    r    = cfg["sizes"]["indicator_r"]
    col  = _hex(cfg["colors"]["accent"])
    font = _get_font(cfg, "semibold", cfg["sizes"]["indicator_text"])
    text = f"{num}/{total}"
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    bb = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (bb[2] - bb[0]) // 2, cy - (bb[3] - bb[1]) // 2),
              text, font=font, fill=_hex(cfg["colors"]["white"]))


def _num_circle(draw: ImageDraw.Draw, cx: int, cy: int, num: int, cfg: dict) -> None:
    """Зелёный кружок с номером — левый верхний угол внутренних слайдов."""
    r    = cfg["sizes"]["num_circle_r"]
    col  = _hex(cfg["colors"]["accent"])
    font = _get_font(cfg, "semibold", cfg["sizes"]["num_circle_text"])
    text = str(num)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    bb = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (bb[2] - bb[0]) // 2, cy - (bb[3] - bb[1]) // 2),
              text, font=font, fill=_hex(cfg["colors"]["white"]))


def _dots(draw: ImageDraw.Draw, slide_num: int, total: int, cfg: dict, W: int, cy: int) -> None:
    """Индикатор прогресса снизу по центру."""
    r   = cfg["sizes"]["dot_r"]
    gap = cfg["sizes"]["dot_gap"]
    acc = _hex(cfg["colors"]["accent"])
    inact = _hex(cfg["colors"]["lines"])

    total_w = total * (r * 2) + (total - 1) * gap
    x0 = (W - total_w) // 2

    for i in range(total):
        cx = x0 + i * (r * 2 + gap) + r
        if i == slide_num - 1:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=acc)
        else:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=inact, width=2)


def _accent_box(draw: ImageDraw.Draw, x: int, y: int, w: int, text: str, cfg: dict) -> int:
    """Светло-зелёная карточка с текстом. Возвращает нижний y."""
    pad  = cfg["layout"]["box_padding"]
    rad  = cfg["layout"]["box_radius"]
    font = _get_font(cfg, "regular", cfg["sizes"]["box_text"])
    gap  = cfg["layout"]["line_gap"]

    lines = _wrap(text, font, w - pad * 2, draw)
    lh    = _line_h(font, draw, gap)
    bh    = len(lines) * lh + pad * 2

    fill = _hex(cfg["colors"]["accent_light"])
    try:
        draw.rounded_rectangle([x, y, x + w, y + bh], radius=rad, fill=fill)
    except AttributeError:
        draw.rectangle([x, y, x + w, y + bh], fill=fill)

    ty = y + pad
    for line in lines:
        draw.text((x + pad, ty), line, font=font, fill=_hex(cfg["colors"]["text_secondary"]))
        ty += lh

    return y + bh


def _divider(draw: ImageDraw.Draw, x: int, y: int, w: int, cfg: dict) -> None:
    col = _hex(cfg["colors"]["lines"])
    draw.rectangle([x, y, x + w, y + 2], fill=col)


# ─────────────────────────────────────────────────────────────
# ШАБЛОНЫ СЛАЙДОВ
# ─────────────────────────────────────────────────────────────

def _slide1_t1(draw: ImageDraw.Draw, W: int, H: int, slide: dict, total: int, cfg: dict) -> None:
    """Шаблон 1, слайд 1 (обложка): логотип + крупный заголовок + зелёный подзаголовок."""
    pad = cfg["layout"]["pad"]
    cw  = W - pad * 2

    # Логотип
    _logo(draw, pad, pad, cfg)

    # Декоративные звёздочки (правая верхняя зона)
    acc = _hex(cfg["colors"]["accent"])
    for sp in cfg["layout"]["sparkle_positions"]:
        _sparkle(draw, W + sp["x"], sp["y"], sp["r"], acc)

    # Разделяем текст
    text = slide.get("text", "")
    headline, green_sub, support = _split_hook(text)

    # Рабочая вертикальная зона — под логотипом, над подвалом
    y_top    = pad + cfg["sizes"]["logo_icon"] + cfg["layout"]["after_logo_gap"]
    y_bottom = H - pad - cfg["sizes"]["indicator_r"] * 2 - 40  # место под индикатор
    area_h   = y_bottom - y_top

    # Подсчёт высот блоков для центрирования
    hl_max_h  = area_h * 2 // 5
    grn_max_h = area_h * 2 // 5
    sup_h     = cfg["sizes"]["support_text"] + 16 if support else 0

    hl_lines, hl_font, hl_lh = _fit(
        headline, draw, cfg, "extrabold",
        cfg["sizes"]["h1_max"], cfg["sizes"]["h1_min"],
        cw, hl_max_h,
    )
    grn_lines, grn_font, grn_lh = ([], None, 0)
    if green_sub:
        grn_lines, grn_font, grn_lh = _fit(
            green_sub, draw, cfg, "semibold",
            cfg["sizes"]["h1_green_max"], cfg["sizes"]["h1_green_min"],
            cw, grn_max_h,
        )

    total_block_h = (len(hl_lines) * hl_lh
                     + (16 if green_sub else 0)
                     + len(grn_lines) * grn_lh
                     + (sup_h + 20 if support else 0))

    # Вертикальное выравнивание — сдвигаем вниз от центра (как в макете)
    y = y_top + max(0, (area_h - total_block_h) // 3)

    # Тёмный заголовок
    for line in hl_lines:
        draw.text((pad, y), line, font=hl_font, fill=_hex(cfg["colors"]["text_primary"]))
        y += hl_lh

    # Зелёный подзаголовок
    if grn_lines:
        y += 16
        for line in grn_lines:
            draw.text((pad, y), line, font=grn_font, fill=_hex(cfg["colors"]["accent"]))
            y += grn_lh

    # Мелкий поддерживающий текст
    if support:
        y += 24
        sup_font = _get_font(cfg, "regular", cfg["sizes"]["support_text"])
        draw.text((pad, y), support, font=sup_font, fill=_hex(cfg["colors"]["text_secondary"]))

    # Индикатор «1/N» — правый нижний угол
    ir = cfg["sizes"]["indicator_r"]
    _indicator(draw, W - pad - ir, H - pad - ir, 1, total, cfg)


def _slide_inner(
    draw: ImageDraw.Draw, W: int, H: int,
    slide: dict, slide_num: int, total: int, is_last: bool, cfg: dict,
) -> None:
    """Шаблон 1, слайды 2–4: номер-кружок + заголовок + тело + индикатор."""
    pad = cfg["layout"]["pad"]
    cw  = W - pad * 2
    nr  = cfg["sizes"]["num_circle_r"]

    # Номер-кружок
    _num_circle(draw, pad + nr, pad + nr, slide_num, cfg)

    # Начало текстового блока
    y = pad + nr * 2 + cfg["layout"]["after_circle_y"]

    # Подвальный резерв: точки + (логотип на последнем)
    dot_reserve  = cfg["sizes"]["dot_r"] * 2 + 40
    last_reserve = 60 if is_last else 0
    bottom_y     = H - pad - dot_reserve - last_reserve
    avail_h      = bottom_y - y

    # Разбиваем текст
    text = slide.get("text", "")
    headline, body = _split_body(text)

    # Заголовок (занимает ~45% области)
    hl_max_h = avail_h * 45 // 100
    hl_lines, hl_font, hl_lh = _fit(
        headline, draw, cfg, "extrabold",
        cfg["sizes"]["h2_max"], cfg["sizes"]["h2_min"],
        cw, hl_max_h,
    )
    for line in hl_lines:
        draw.text((pad, y), line, font=hl_font, fill=_hex(cfg["colors"]["text_primary"]))
        y += hl_lh

    y += cfg["layout"]["heading_gap"]

    # Разделительная линия
    if y < bottom_y - 80:
        _divider(draw, pad, y, cw, cfg)
        y += 16

    # Тело
    if body and y < bottom_y - 60:
        body_max_h = bottom_y - y - (cfg["layout"]["box_padding"] * 2 + 20 if len(body) > 70 else 0)

        if len(body) > 70 and y + 80 < bottom_y:
            # Карточка-акцент
            _accent_box(draw, pad, y, cw, body, cfg)
        else:
            body_lines, body_font, body_lh = _fit(
                body, draw, cfg, "regular",
                cfg["sizes"]["body_max"], cfg["sizes"]["body_min"],
                cw, body_max_h,
            )
            for line in body_lines:
                draw.text((pad, y), line, font=body_font,
                          fill=_hex(cfg["colors"]["text_secondary"]))
                y += body_lh

    # Последний слайд: курсивный CTA + логотип
    if is_last:
        cta_text = cfg["brand"]["cta_last"]
        cta_font = _get_font(cfg, "regular", cfg["sizes"]["cta_last"])
        draw.text((pad, H - pad - dot_reserve - 50),
                  cta_text, font=cta_font, fill=_hex(cfg["colors"]["accent"]))
        _logo(draw, W - pad - 250, H - pad - 42, cfg)

    # Точки прогресса
    dot_cy = H - pad - cfg["sizes"]["dot_r"] - 8
    _dots(draw, slide_num, total, cfg, W, dot_cy)


def _slide1_t2(draw: ImageDraw.Draw, W: int, H: int, slide: dict, total: int, cfg: dict) -> None:
    """Шаблон 2, слайд 1: крупная цифра + подпись."""
    pad = cfg["layout"]["pad"]
    cw  = W - pad * 2

    # Логотип
    _logo(draw, pad, pad, cfg)

    text = slide.get("text", "").strip()
    m    = re.match(r'^(\d[\d\s%.,]*)', text)
    number = m.group(1).strip() if m else text[:3]
    rest   = text[len(m.group(0)):].strip() if m else ""

    # Крупная цифра
    num_font = _get_font(cfg, "extrabold", cfg["sizes"]["number_huge"])
    nb  = draw.textbbox((0, 0), number, font=num_font)
    nw, nh = nb[2] - nb[0], nb[3] - nb[1]
    nx  = (W - nw) // 2
    ny  = H // 2 - nh // 2 - 80
    draw.text((nx, ny), number, font=num_font, fill=_hex(cfg["colors"]["accent"]))

    # Текст под цифрой
    if rest:
        sub_max_h = H - (ny + nh + 30) - pad - 120
        sub_lines, sub_font, sub_lh = _fit(
            rest, draw, cfg, "semibold",
            cfg["sizes"]["number_subtitle"], 28,
            cw, sub_max_h,
        )
        sy = ny + nh + 30
        for line in sub_lines:
            bb = draw.textbbox((0, 0), line, font=sub_font)
            draw.text(((W - (bb[2] - bb[0])) // 2, sy),
                      line, font=sub_font, fill=_hex(cfg["colors"]["text_primary"]))
            sy += sub_lh

    # CTA "Проверь себя →"
    cta_font = _get_font(cfg, "regular", 28)
    draw.text((pad, H - pad - 110), "Проверь себя →",
              font=cta_font, fill=_hex(cfg["colors"]["text_secondary"]))

    # Индикатор
    ir = cfg["sizes"]["indicator_r"]
    _indicator(draw, W - pad - ir, H - pad - ir, 1, total, cfg)


# ─────────────────────────────────────────────────────────────
# ПУБЛИЧНЫЙ API
# ─────────────────────────────────────────────────────────────

def _detect_template(slides: list[dict]) -> str:
    """Шаблон 2 если текст первого слайда начинается с цифры."""
    if not slides:
        return "1"
    return "2" if re.match(r'^\d', slides[0].get("text", "").strip()) else "1"


def render_slide(
    slide: dict, slide_num: int, total: int,
    template: str, cfg: dict, output_path: Path,
) -> Path:
    W  = cfg["canvas"]["width"]
    H  = cfg["canvas"]["height"]
    bg = _hex(cfg["colors"]["bg"])

    img  = Image.new("RGB", (W, H), color=bg)
    draw = ImageDraw.Draw(img)

    if slide_num == 1 and template == "2":
        _slide1_t2(draw, W, H, slide, total, cfg)
    elif slide_num == 1:
        _slide1_t1(draw, W, H, slide, total, cfg)
    else:
        is_last = (slide_num == total)
        _slide_inner(draw, W, H, slide, slide_num, total, is_last, cfg)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", optimize=True)
    logger.info(f"[Renderer] Слайд {slide_num}/{total} → {output_path.name}")
    return output_path


def render_carousel(slides: list[dict], output_dir: Path, spec_id: str) -> dict[str, str]:
    """
    Рендерит карусель. Всегда 3–4 слайда (обрезает лишние).
    Возвращает {slide_num_str: path_str}.
    """
    # Жёсткое ограничение: максимум 4 слайда
    if len(slides) > 4:
        logger.warning(f"[Renderer] LLM вернул {len(slides)} слайдов — обрезаем до 4")
        slides = slides[:4]
    if len(slides) < 3:
        logger.warning(f"[Renderer] Мало слайдов: {len(slides)} (минимум 3)")

    cfg      = _load_design()
    template = _detect_template(slides)
    total    = len(slides)
    result: dict[str, str] = {}

    logger.info(f"[Renderer] Карусель {spec_id}: {total} слайдов, шаблон {template}")

    for i, slide in enumerate(slides):
        slide_num = slide.get("slide", i + 1)
        out_path  = Path(output_dir) / f"{spec_id}_carousel_slide{slide_num}.png"
        try:
            render_slide(slide, slide_num, total, template, cfg, out_path)
            result[str(slide_num)] = str(out_path)
        except Exception as e:
            logger.error(f"[Renderer] Ошибка слайда {slide_num}: {e}", exc_info=True)

    return result


# ─────────────────────────────────────────────────────────────
# PHOTO CAROUSEL  (1080 × 1350, Instagram 4:5)
# ─────────────────────────────────────────────────────────────

_PH_W        = 1080
_PH_H        = 1350
_PH_PAD      = 80
_PH_SUPPORT  = {".jpg", ".jpeg", ".png", ".webp"}
_PHOTOS_DIR  = _ROOT / "assets" / "photos"
_TIPS_DIR    = _ROOT / "assets" / "photos_tips"


def _ph_pick(n: int, lib: Path) -> list[Path]:
    """Возвращает n уникальных фото из библиотеки (повторы если мало)."""
    lib.mkdir(parents=True, exist_ok=True)
    all_p = [p for p in lib.rglob("*") if p.is_file() and p.suffix.lower() in _PH_SUPPORT]
    if not all_p:
        raise ValueError(f"Фотобиблиотека пуста: {lib}")
    random.shuffle(all_p)
    if len(all_p) >= n:
        return all_p[:n]
    result: list[Path] = []
    while len(result) < n:
        result.extend(all_p)
    return result[:n]


def _ph_open_crop(path: Path, W: int, H: int) -> Image.Image | None:
    """Открывает фото и обрезает до W×H по центру."""
    try:
        img = Image.open(path).convert("RGB")
    except Exception as e:
        logger.warning(f"[Photo] Не открыть {path.name}: {e}")
        return None
    src_r = img.width / img.height
    tgt_r = W / H
    if src_r > tgt_r:
        new_w, new_h = int(H * src_r), H
    else:
        new_w, new_h = W, int(W / src_r)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    return img.crop(((new_w - W) // 2, (new_h - H) // 2,
                     (new_w - W) // 2 + W, (new_h - H) // 2 + H))


def _ph_zone_stats(img: Image.Image, W: int, H: int) -> dict:
    """Анализ яркости/детальности 3 зон через 54×67 thumbnail."""
    tw, th = 54, 67
    thumb = img.convert("L").resize((tw, th), Image.LANCZOS)
    sx, sy = W / tw, H / th
    defs = {
        "top":    (0, 0,              tw, int(th * 0.40)),
        "bottom": (0, int(th * 0.60), tw, th),
        "center": (int(tw * 0.25), int(th * 0.28), int(tw * 0.75), int(th * 0.72)),
    }
    out = {}
    for name, (x0, y0, x1, y1) in defs.items():
        pix = list(thumb.crop((x0, y0, x1, y1)).getdata())
        n = len(pix) or 1
        mean = sum(pix) / n
        std  = (sum((p - mean) ** 2 for p in pix) / n) ** 0.5
        out[name] = {
            "mean":  mean,
            "std":   std,
            # Высокий score = меньше деталей + экстремальная яркость
            "score": (128 - std) * 0.65 + abs(mean - 128) * 0.35,
        }
    return out


def _ph_best_zone(stats: dict, slide_idx: int) -> str:
    """Для обложки (idx=0) предпочитаем bottom; иначе лучший по score."""
    if slide_idx == 0 and stats["bottom"]["std"] < 65:
        return "bottom"
    if slide_idx == 0 and stats["top"]["std"] < 65:
        return "top"
    return max(stats, key=lambda z: stats[z]["score"])


def _ph_gradient(img: Image.Image, zone: str, W: int, H: int) -> Image.Image:
    """Направленный градиент (чёрный полупрозрачный) в зоне текста."""
    MAX_A = 150
    BANDS = 40

    if zone == "bottom":
        gw, gh, gx, gy = W, int(H * 0.56), 0, int(H * 0.44)
        mask = Image.new("L", (gw, gh), 0)
        dm = ImageDraw.Draw(mask)
        for i in range(BANDS):
            a = int(MAX_A * (i / BANDS) ** 0.55)
            y0, y1 = int(i * gh / BANDS), int((i + 1) * gh / BANDS)
            dm.rectangle([0, y0, gw, y1], fill=a)
    elif zone == "top":
        gw, gh, gx, gy = W, int(H * 0.50), 0, 0
        mask = Image.new("L", (gw, gh), 0)
        dm = ImageDraw.Draw(mask)
        for i in range(BANDS):
            a = int(MAX_A * ((BANDS - i) / BANDS) ** 0.55)
            y0, y1 = int(i * gh / BANDS), int((i + 1) * gh / BANDS)
            dm.rectangle([0, y0, gw, y1], fill=a)
    else:  # center
        gw, gh = int(W * 0.80), int(H * 0.54)
        gx, gy = (W - gw) // 2, (H - gh) // 2
        mask = Image.new("L", (gw, gh), int(MAX_A * 0.5))

    black = Image.new("RGB", (gw, gh), (0, 0, 0))
    out = img.copy()
    out.paste(black, (gx, gy), mask)
    return out


def _ph_text_color(zone_mean: float, gradient: bool) -> tuple[int, int, int]:
    effective = zone_mean * 0.45 if gradient else zone_mean
    return (255, 255, 255) if effective < 150 else (28, 28, 28)


def _ph_shadow(col: tuple[int, int, int]) -> tuple[int, int, int]:
    return (30, 30, 30) if col[0] > 128 else (210, 210, 210)


def _ph_text_area(zone: str, W: int, H: int, pad: int, logo_h: int) -> tuple[int, int, int, int]:
    """Возвращает (x, y, w, h) текстовой области."""
    if zone == "bottom":
        ty = int(H * 0.46)
        return pad, ty, W - pad * 2, H - ty - pad - 60
    elif zone == "top":
        ty = pad + logo_h + 24
        return pad, ty, W - pad * 2, int(H * 0.44) - ty
    else:  # center
        ty = int(H * 0.28)
        return pad, ty, W - pad * 2, int(H * 0.44)


def _ph_draw_text(
    draw: ImageDraw.Draw,
    text: str,
    cfg: dict,
    tx: int, ty: int, tw: int, th: int,
    text_col: tuple,
    slide_idx: int,
) -> int:
    """Рисует текст с тенью в заданной области. Возвращает размер шрифта."""
    gap     = cfg["layout"]["line_gap"] + 6
    variant = "extrabold" if slide_idx == 0 else "semibold"
    sz_max  = 88 if slide_idx == 0 else 72
    sz_min  = 36
    shadow  = _ph_shadow(text_col)

    raw_lines = [l.strip() for l in text.split("\n") if l.strip()]

    best_lines: list[str] = []
    best_size = sz_min

    for size in range(sz_max, sz_min - 1, -4):
        font = _get_font(cfg, variant, size)
        lines: list[str] = []
        for raw in raw_lines:
            lines.extend(_wrap(raw, font, tw, draw))
        lh = draw.textbbox((0, 0), "Ащ", font=font)[3] + gap
        if len(lines) * lh <= th:
            best_lines = lines
            best_size  = size
            break

    if not best_lines:
        font = _get_font(cfg, variant, sz_min)
        for raw in raw_lines:
            best_lines.extend(_wrap(raw, font, tw, draw))

    font = _get_font(cfg, variant, best_size)
    lh   = draw.textbbox((0, 0), "Ащ", font=font)[3] + gap
    total_h = len(best_lines) * lh
    y = ty + max(0, (th - total_h) // 2)

    for line in best_lines:
        draw.text((tx + 2, y + 2), line, font=font, fill=shadow)
        draw.text((tx, y),         line, font=font, fill=text_col)
        y += lh

    return best_size


def _ph_logo(draw: ImageDraw.Draw, x: int, y: int, cfg: dict, text_col: tuple) -> int:
    """Логотип адаптированный под фото-фон. Возвращает высоту блока."""
    sz = 32
    accent = _hex(cfg["colors"]["accent"])
    _house_icon(draw, x, y, sz, accent, text_col)
    font   = _get_font(cfg, "semibold", 20)
    shadow = _ph_shadow(text_col)
    lx, ly = x + sz + 10, y + (sz - 20) // 2
    draw.text((lx + 1, ly + 1), cfg["brand"]["name"], font=font, fill=shadow)
    draw.text((lx, ly),          cfg["brand"]["name"], font=font, fill=text_col)
    return sz


def _ph_indicator(draw: ImageDraw.Draw, W: int, H: int, num: int, total: int, cfg: dict) -> None:
    pad, r = _PH_PAD, 36
    cx, cy = W - pad - r, H - pad - r
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_hex(cfg["colors"]["accent"]))
    font = _get_font(cfg, "semibold", 24)
    text = f"{num}/{total}"
    bb   = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (bb[2] - bb[0]) // 2, cy - (bb[3] - bb[1]) // 2),
              text, font=font, fill=(255, 255, 255))


def _ph_dots(draw: ImageDraw.Draw, slide_num: int, total: int, W: int, H: int) -> None:
    pad, r, gap = _PH_PAD, 7, 14
    total_w = total * r * 2 + (total - 1) * gap
    x0 = (W - total_w) // 2
    cy = H - pad - r - 10
    for i in range(total):
        cx = x0 + i * (r * 2 + gap) + r
        if i == slide_num - 1:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255))
        else:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(180, 180, 180), width=2)


def render_photo_slide(
    slide: dict,
    slide_idx: int,
    total: int,
    photo_path: Path,
    cfg: dict,
    output_path: Path,
) -> tuple[Path, dict]:
    """Рендерит один слайд на фото-фоне (1080×1350). Возвращает (путь, мета)."""
    W, H = _PH_W, _PH_H

    img = _ph_open_crop(photo_path, W, H)
    if img is None:
        img = Image.new("RGB", (W, H), _hex(cfg["colors"]["bg"]))

    stats     = _ph_zone_stats(img, W, H)
    zone      = _ph_best_zone(stats, slide_idx)
    zone_mean = stats[zone]["mean"]

    gradient = (70 < zone_mean < 185) or stats[zone]["std"] > 40
    if gradient:
        img = _ph_gradient(img, zone, W, H)

    text_col = _ph_text_color(zone_mean, gradient)
    draw     = ImageDraw.Draw(img)

    logo_h = _ph_logo(draw, _PH_PAD, _PH_PAD, cfg, text_col)

    tx, ty, tw, th = _ph_text_area(zone, W, H, _PH_PAD, logo_h)
    font_size = _ph_draw_text(
        draw, slide.get("text", ""), cfg, tx, ty, tw, th, text_col, slide_idx
    )

    slide_num = slide_idx + 1
    if slide_idx == 0:
        _ph_indicator(draw, W, H, 1, total, cfg)
    else:
        _ph_dots(draw, slide_num, total, W, H)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", optimize=True)

    meta = {
        "photo":      str(photo_path),
        "zone":       zone,
        "text_color": "white" if text_col[0] > 128 else "dark",
        "gradient":   gradient,
        "font_size":  font_size,
        "zone_mean":  round(zone_mean, 1),
        "zone_std":   round(stats[zone]["std"], 1),
    }
    logger.info(
        f"[Photo] {slide_num}/{total} зона={zone} "
        f"цвет={'белый' if text_col[0]>128 else 'тёмный'} "
        f"градиент={gradient} шрифт={font_size}"
    )
    return output_path, meta


def render_photo_carousel(
    slides: list[dict],
    output_dir: Path,
    spec_id: str,
    use_tips: bool = False,
) -> dict[str, str]:
    """
    Рендерит карусель на фото (1080×1350 px, Instagram 4:5).
    Возвращает {slide_num_str: path_str}.
    Сохраняет метаданные в {spec_id}_photo_meta.json.
    """
    import json as _json

    if len(slides) > 4:
        logger.warning(f"[Photo] Обрезаем до 4 слайдов ({len(slides)} получено)")
        slides = slides[:4]

    cfg     = _load_design()
    lib_dir = _TIPS_DIR if use_tips else _PHOTOS_DIR
    photos  = _ph_pick(len(slides), lib_dir)

    total      = len(slides)
    result:    dict[str, str]  = {}
    all_meta:  dict[str, dict] = {}
    output_dir = Path(output_dir)

    logger.info(f"[Photo] Карусель {spec_id}: {total} слайдов, библиотека={lib_dir.name}")

    for i, slide in enumerate(slides):
        slide_num = slide.get("slide", i + 1)
        out_path  = output_dir / f"{spec_id}_photo_slide{slide_num}.png"
        try:
            saved, meta = render_photo_slide(slide, i, total, photos[i], cfg, out_path)
            result[str(slide_num)]   = str(saved)
            all_meta[str(slide_num)] = meta
        except Exception as e:
            logger.error(f"[Photo] Ошибка слайда {slide_num}: {e}", exc_info=True)

    try:
        meta_path = output_dir / f"{spec_id}_photo_meta.json"
        meta_path.write_text(
            _json.dumps(all_meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass

    return result
