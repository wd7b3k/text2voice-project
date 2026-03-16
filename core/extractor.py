"""
core/extractor.py — извлечение текста из PDF, DOCX, DJVU
"""

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pdfplumber
from docx import Document

logger = logging.getLogger(__name__)


def extract_text(file_path: str) -> str:
    """
    Определяет формат файла и извлекает текст.
    Возвращает очищенный текст.
    """
    ext = Path(file_path).suffix.lower()

    extractors = {
        ".pdf":  _extract_pdf,
        ".docx": _extract_docx,
        ".doc":  _extract_doc,
        ".djvu": _extract_djvu,
    }

    if ext not in extractors:
        raise ValueError(f"Неподдерживаемый формат: {ext}")

    raw_text = extractors[ext](file_path)
    return clean_text(raw_text)


def _extract_pdf(path: str) -> str:
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n".join(pages)


def _extract_docx(path: str) -> str:
    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def _extract_doc(path: str) -> str:
    """Конвертация .doc через LibreOffice (нужен libreoffice-writer)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "docx",
             "--outdir", tmpdir, path],
            capture_output=True, timeout=120
        )
        if result.returncode != 0:
            raise RuntimeError(f"LibreOffice ошибка: {result.stderr.decode()}")
        docx_files = list(Path(tmpdir).glob("*.docx"))
        if not docx_files:
            raise RuntimeError("LibreOffice не создал docx")
        return _extract_docx(str(docx_files[0]))


def _extract_djvu(path: str) -> str:
    """Конвертация DJVU через djvutxt (нужен djvulibre)."""
    result = subprocess.run(
        ["djvutxt", path],
        capture_output=True, timeout=300
    )
    if result.returncode != 0:
        raise RuntimeError(f"djvutxt ошибка: {result.stderr.decode()}")
    return result.stdout.decode("utf-8", errors="replace")


def clean_text(text: str) -> str:
    """
    Очистка текста:
    - удаление колонтитулов (короткие строки в начале/конце страниц)
    - удаление номеров страниц
    - удаление сносок [1], [a], (1)
    - нормализация пробелов и переносов
    """
    # Удаляем строки, состоящие только из цифры (номера страниц)
    text = re.sub(r"(?m)^\s*\d{1,4}\s*$", "", text)

    # Удаляем сноски [1], [12], [a]
    text = re.sub(r"\[\w{1,4}\]", "", text)

    # Удаляем висячие дефисы (перенос слов)
    text = re.sub(r"-\s*\n\s*", "", text)

    # Нормализуем множественные пустые строки
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Удаляем строки короче 3 символов (обычно мусор)
    lines = [line for line in text.split("\n") if len(line.strip()) >= 3 or not line.strip()]
    text = "\n".join(lines)

    return text.strip()
