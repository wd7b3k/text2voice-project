import logging
import os

logger = logging.getLogger(__name__)


class CoquiTTSEngine:
    def __init__(self):
        from TTS.api import TTS
        model = os.getenv("TTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
        logger.info(f"Загружаем TTS модель: {model}")
        self.tts = TTS(model, progress_bar=False)
        self.language = os.getenv("TTS_LANGUAGE", "ru")
        self.speaker_wav = "/tmp/speaker.wav"
        logger.info("TTS модель загружена")

    def synthesize(self, text, output_path):
        self.tts.tts_to_file(
            text=text,
            file_path=output_path,
            language=self.language,
            speaker_wav=self.speaker_wav,
            split_sentences=True,
        )
        return output_path


_engine_instance = None


def get_tts_engine():
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = CoquiTTSEngine()
        logger.info("TTS движок: coqui")
    return _engine_instance
