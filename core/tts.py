"""
core/tts.py — движок синтеза речи
Поддерживает: CoquiTTS (локально), ElevenLabs (API)
"""

import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class TTSEngine(ABC):
    @abstractmethod
    def synthesize(self, text: str, output_path: str) -> str:
        """Синтезировать речь. Вернуть путь к mp3."""


class CoquiTTSEngine(TTSEngine):
    """
    CoquiTTS XTTS v2 — локально, высокое качество, русский язык.
    Требует GPU для быстрой работы (работает и на CPU, но медленнее).
    """

    def __init__(self):
        from TTS.api import TTS
        model = os.getenv("TTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
        logger.info(f"Загружаем TTS модель: {model}")
        self.tts = TTS(model)
        self.language = os.getenv("TTS_LANGUAGE", "ru")
        logger.info("TTS модель загружена")

    def synthesize(self, text: str, output_path: str) -> str:
        self.tts.tts_to_file(
            text=text,
            file_path=output_path,
            language=self.language,
            split_sentences=True,  # правильные паузы между предложениями
        )
        return output_path


class ElevenLabsEngine(TTSEngine):
    """
    ElevenLabs API — лучшее качество голоса, платный сервис.
    Подходит если не хватает ресурсов VPS для CoquiTTS.
    """

    def __init__(self):
        from elevenlabs import ElevenLabs
        self.client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
        self.voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

    def synthesize(self, text: str, output_path: str) -> str:
        import io
        audio = self.client.generate(
            text=text,
            voice=self.voice_id,
            model="eleven_multilingual_v2"
        )
        with open(output_path, "wb") as f:
            for chunk in audio:
                f.write(chunk)
        return output_path


# Фабрика — выбор движка из .env
_engine_instance: TTSEngine | None = None


def get_tts_engine() -> TTSEngine:
    global _engine_instance
    if _engine_instance is None:
        engine_name = os.getenv("TTS_ENGINE", "coqui").lower()
        if engine_name == "elevenlabs":
            _engine_instance = ElevenLabsEngine()
        else:
            _engine_instance = CoquiTTSEngine()
        logger.info(f"TTS движок: {engine_name}")
    return _engine_instance
