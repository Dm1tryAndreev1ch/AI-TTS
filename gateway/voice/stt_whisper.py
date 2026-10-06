import asyncio
import numpy as np


class WhisperStt:
    """faster-whisper on CPU (int8). On Apple Silicon faster-whisper has no Metal support."""

    def __init__(self, model_size: str = "small", compute_type: str = "int8", language: str = "ru") -> None:
        from faster_whisper import WhisperModel
        self._model = WhisperModel(model_size, device="cpu", compute_type=compute_type)
        self._language = language

    def _run(self, pcm: bytes) -> str:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            audio, language=self._language, beam_size=1, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()

    async def transcribe(self, pcm: bytes) -> str:
        return await asyncio.to_thread(self._run, pcm)
