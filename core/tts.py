import logging
import os
import time

logger = logging.getLogger(__name__)


class CoquiTTSEngine:
    def __init__(self):
        from TTS.api import TTS

        models_raw = os.getenv(
            "TTS_MODEL_CANDIDATES",
            "tts_models/ru/v3_1/aidar,tts_models/multilingual/multi-dataset/xtts_v2",
        )
        model_candidates = [m.strip() for m in models_raw.split(",") if m.strip()]
        self.model_name = None
        self.tts = None

        for model in model_candidates:
            try:
                logger.info(f"Пробуем загрузить TTS модель: {model}")
                started = time.monotonic()
                self.tts = TTS(model, progress_bar=False)
                self.model_name = model
                logger.info(
                    "TTS модель загружена: %s (%.1f c)",
                    model,
                    time.monotonic() - started,
                )
                break
            except Exception as exc:
                logger.warning("Не удалось загрузить модель %s: %s", model, exc)

        if self.tts is None:
            raise RuntimeError("Не удалось загрузить ни одну TTS модель")

        self.language = os.getenv("TTS_LANGUAGE", "ru")
        self.speaker_wav = "/tmp/speaker.wav"

        try:
            import torch

            cpu_threads = int(os.getenv("TTS_CPU_THREADS", str(os.cpu_count() or 4)))
            torch.set_num_threads(cpu_threads)
            torch.set_num_interop_threads(max(1, cpu_threads // 2))
            logger.info("Torch threads: intra=%s inter=%s", cpu_threads, max(1, cpu_threads // 2))
        except Exception as exc:
            logger.warning("Не удалось настроить torch threads: %s", exc)

    def synthesize(self, text, output_path):
        clean_text = " ".join((text or "").split())
        kwargs = {
            "text": clean_text,
            "file_path": output_path,
            "split_sentences": True,
        }

        if "xtts" in (self.model_name or ""):
            kwargs["language"] = self.language
            kwargs["speaker_wav"] = self.speaker_wav

        self.tts.tts_to_file(**kwargs)
        return output_path


_engine_instance = None


def get_tts_engine():
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = CoquiTTSEngine()
        logger.info("TTS движок: coqui")
    return _engine_instance
