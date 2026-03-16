"""
core/security.py — шифрование файлов пользователей (AES-256 через Fernet)
"""

import hashlib
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    key = os.getenv("FILE_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("FILE_ENCRYPTION_KEY не задан в .env")
    return Fernet(key.encode())


def encrypt_file(src_path: str) -> str:
    """
    Шифрует файл AES-256. 
    Исходный файл удаляется, возвращает путь к .enc файлу.
    """
    f = _get_fernet()
    src = Path(src_path)
    enc_path = str(src) + ".enc"

    with open(src, "rb") as fp:
        encrypted = f.encrypt(fp.read())
    with open(enc_path, "wb") as fp:
        fp.write(encrypted)

    src.unlink()  # удаляем нешифрованный оригинал
    logger.debug(f"Зашифровано: {enc_path}")
    return enc_path


def decrypt_file(enc_path: str, dest_path: str) -> str:
    """
    Расшифровывает файл для отправки пользователю.
    enc_path  — зашифрованный файл
    dest_path — куда сохранить расшифрованный
    """
    f = _get_fernet()
    with open(enc_path, "rb") as fp:
        decrypted = f.decrypt(fp.read())
    with open(dest_path, "wb") as fp:
        fp.write(decrypted)
    return dest_path


def file_hash(file_bytes: bytes) -> str:
    """SHA-256 хеш файла для кэширования."""
    return hashlib.sha256(file_bytes).hexdigest()


def safe_filename(original_name: str) -> str:
    """
    Очищает имя файла от опасных символов.
    'Война и Мир.pdf' → 'Война_и_Мир'
    """
    stem = Path(original_name).stem
    # оставляем буквы, цифры, пробелы, дефисы
    clean = "".join(c if c.isalnum() or c in " -_" else "_" for c in stem)
    clean = "_".join(clean.split())  # заменяем пробелы на _
    return clean[:100]  # ограничение длины


def make_mp3_filename(original_name: str, chapter_index: int, chapter_title: str) -> str:
    """
    Формирует имя выходного mp3 файла.
    'Война_и_Мир_ch01_Введение.mp3'
    """
    base = safe_filename(original_name)
    title_clean = safe_filename(chapter_title)[:40]
    return f"{base}_ch{chapter_index:02d}_{title_clean}.mp3"
