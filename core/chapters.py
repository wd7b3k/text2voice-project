import re
from dataclasses import dataclass


@dataclass
class Chapter:
    index: int
    title: str
    content: str


# Паттерны без inline-флагов (?m) — флаг передаётся в re.split отдельно
CHAPTER_PATTERNS = [
    r"(Глава\s+(?:\d+|[IVXLC]+|[А-Яа-я]+)[^\n]{0,60})",
    r"(Chapter\s+(?:\d+|[IVXLC]+|\w+)[^\n]{0,60})",
    r"(Часть\s+(?:\d+|[А-Яа-я]+)[^\n]{0,60})",
    r"(\d{1,2}(?:\.\d{1,2})?\.?\s+[А-ЯA-Z][^\n]{3,80})",
    r"([А-ЯЁ\s]{5,50})",
]

COMBINED_PATTERN = "|".join(CHAPTER_PATTERNS)
MAX_CHARS_PER_CHUNK = 4500
MIN_CHAPTER_CHARS   = 200


def split_into_chapters(text: str) -> list:
    parts = re.split(COMBINED_PATTERN, text, flags=re.MULTILINE)

    if len(parts) < 3:
        return _split_by_size(text, "Текст")

    raw_chapters = []
    intro = parts[0].strip()
    if len(intro) > MIN_CHAPTER_CHARS:
        raw_chapters.append(("Введение", intro))

    i = 1
    while i < len(parts):
        title = None
        for j in range(i, min(i + len(CHAPTER_PATTERNS) * 2, len(parts))):
            if parts[j] and parts[j].strip():
                title = parts[j].strip()
                i = j + 1
                break
        if title is None:
            break
        content = parts[i].strip() if i < len(parts) and parts[i] is not None else ""
        i += 1
        if len(content) >= MIN_CHAPTER_CHARS:
            raw_chapters.append((title, content))

    if not raw_chapters:
        return _split_by_size(text, "Текст")

    result = []
    for ch_title, ch_content in raw_chapters:
        chunks = _split_by_size(ch_content, ch_title)
        result.extend(chunks)

    for idx, ch in enumerate(result, 1):
        ch.index = idx

    return result


def _split_by_size(text: str, base_title: str) -> list:
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
        Chapter(index=i + 1, title=f"{base_title} — часть {i + 1}", content=chunk)
        for i, chunk in enumerate(chunks)
    ]
