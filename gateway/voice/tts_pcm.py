import asyncio
import io
import wave
from pathlib import Path

MAX_CACHE = 64


class PiperPcm:
    """Piper synthesis returning raw PCM16 mono and its sample rate (for telephony). One shared voice."""

    def __init__(self, model_path: str) -> None:
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"Piper voice not found: {model_path}")
        from piper import PiperVoice
        self._voice = PiperVoice.load(model_path)
        self._cache: dict[str, tuple[bytes, int]] = {}

    def _synth(self, text: str) -> tuple[bytes, int]:
        if text in self._cache:
            return self._cache[text]
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            self._voice.synthesize_wav(text, out)
        buf.seek(0)
        with wave.open(buf, "rb") as rd:
            if rd.getnchannels() != 1 or rd.getsampwidth() != 2:
                raise ValueError("Piper output must be mono PCM16")
            result = (rd.readframes(rd.getnframes()), rd.getframerate())
        if len(self._cache) < MAX_CACHE:
            self._cache[text] = result
        return result

    async def synth(self, text: str) -> tuple[bytes, int]:
        return await asyncio.to_thread(self._synth, text)
