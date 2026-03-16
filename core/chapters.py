"""
core/chapters.py — разбивка текста на главы
"""

import re
from dataclasses import dataclass


@dataclass
class Chapter:
    index: int
    title: str
    content: str


# Паттерны для определения заголовков глав
CHAPTER_PATTERNS = [
    # Русские: "Глава 1", "Глава первая", "ГЛАВА I"
    r"(?m)^(Глава\s+(?:\d+|[IVXLC]+|[А-Яа-я]+)[^\n]{0,60})$",
    # Английские: "Chapter 1", "CHAPTER ONE"
    r"(?m)^(Chapter\s+(?:\d+|[IVXLC]+|\w+)[^\n]{0,60})$",
    # Части: "Часть 1", "Часть первая"
    r"(?m)^(Часть\s+(?:\d+|[А-Яа-я]+)[^\n]{0,60})$",
    # Нумерованные заголовки: "1. Введение", "2.1 Методология"
    r"(?m)^(\d{1,2}(?:\.\d{1,2})?\.?\s+[А-ЯA-Z][^\n]{3,80})$",
    # Полностью заглавные строки (ВВЕДЕНИЕ, ЗАКЛЮЧЕНИЕ)
    r"(?m)^([А-ЯЁ\s]{5,50})$",
]

COMBINED_PATTERN = "|".join(f"({p})" for p in CHAPTER_PATTERNS)

# Если глава длиннее этого, дробим по абзацам на части
MAX_CHARS_PER_CHUNK = 4500   # ~5 минут аудио на chunk
MIN_CHAPTER_CHARS   = 200    # игнорируем "главы" короче этого


def split_into_chapters(text: str) -> list[Chapter]:
    """
    Разбивает текст на главы по заголовкам.
    Если заголовков нет — делит на равные куски по MAX_CHARS_PER_CHUNK.
    Каждую главу дробит на chunks если она слишком длинная.
    """
    parts = re.split(COMBINED_PATTERN, text)

    chapters = []
    if len(parts) < 3:
        # Заголовков не найдено — делим на куски
        return _split_by_size(text, "Текст")

    # Собираем пары (заголовок, текст)
    raw_chapters: list[tuple[str, str]] = []
    # parts[0] — текст до первой главы (предисловие)
    intro = parts[0].strip()
    if len(intro) > MIN_CHAPTER_CHARS:
        raw_chapters.append(("Введение", intro))

    i = 1
    while i < len(parts):
        # Ищем непустую группу — это заголовок
        title = None
        for j in range(i, min(i + len(CHAPTER_PATTERNS) * 2, len(parts))):
            if parts[j] and parts[j].strip():
                title = parts[j].strip()
                i = j + 1
                break
        if title is None:
            break
        # Следующий непустой — текст главы
        content = parts[i].strip() if i < len(parts) else ""
        i += 1
        if len(content) >= MIN_CHAPTER_CHARS:
            raw_chapters.append((title, content))

    if not raw_chapters:
        return _split_by_size(text, "Текст")

    # Дробим длинные главы на chunks
    result = []
    for ch_title, ch_content in raw_chapters:
        chunks = _split_by_size(ch_content, ch_title)
        result.extend(chunks)

    # Перенумеровываем
    for idx, ch in enumerate(result, 1):
        ch.index = idx

    return result


def _split_by_size(text: str, base_title: str) -> list[Chapter]:
    """Делит текст на куски по MAX_CHARS_PER_CHUNK, разбивая по абзацам."""
    if len(text) <= MAX_CHARS_PER_CHUNK:
        return [Chapter(index=1, title=base_title, content=text)]

    paragraphs = text.split("\n\n")
    chunks = []
    current = []
    current_len = 0

    for para in paragraphs:
        if current_len + len(para) > MAX_CHARS_PER_CHUNK and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += len(para)

    if current:
        chunks.append("\n\n".join(current))

    if len(chunks) == 1:
        return [Chapter(index=1, title=base_title, content=chunks[0])]

    return [
        Chapter(
            index=i + 1,
            title=f"{base_title} — часть {i + 1}",
            content=chunk
        )
        for i, chunk in enumerate(chunks)
    ]
