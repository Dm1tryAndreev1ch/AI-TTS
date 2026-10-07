import asyncio
import os
import shlex
import shutil
import sys
import tempfile
import wave
from pathlib import Path

MAX_CACHE = 64


def default_player() -> tuple[str, ...]:
    """Platform default: winsound (built into Python) on Windows, afplay on macOS, aplay elsewhere."""
    if sys.platform == "win32":
        return ("winsound",)
    if sys.platform == "darwin":
        return ("afplay",)
    return ("aplay",)


def player_from_env(value: str | None) -> tuple[str, ...]:
    """VOICE_PLAYER: empty or 'auto' picks the platform default, anything else is a command line."""
    value = (value or "").strip()
    if not value or value.lower() == "auto":
        return default_player()
    return tuple(shlex.split(value, posix=sys.platform != "win32")) or default_player()


class PiperSpeaker:
    """Synthesizes with Piper into a temp WAV and plays it (winsound on Windows, an external player elsewhere).
    Piper itself is GPL-licensed and each voice has its own license: check both before distributing."""

    def __init__(self, model_path: str, player: tuple[str, ...] | None = None) -> None:
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"Piper voice not found: {model_path}")
        from piper import PiperVoice
        self._voice = PiperVoice.load(model_path)
        self._player = player or default_player()
        self._dir = tempfile.mkdtemp(prefix="piper_")
        self._cache: dict[str, str] = {}
        self._n = 0

    def _synth(self, text: str) -> str:
        if text in self._cache:
            return self._cache[text]
        self._n += 1
        path = os.path.join(self._dir, f"{self._n}.wav")
        with wave.open(path, "wb") as wav_file:
            self._voice.synthesize_wav(text, wav_file)
        if len(self._cache) < MAX_CACHE:
            self._cache[text] = path
        return path

    async def say(self, text: str) -> None:
        path = await asyncio.to_thread(self._synth, text)
        if self._player == ("winsound",):
            import winsound
            await asyncio.to_thread(winsound.PlaySound, path, winsound.SND_FILENAME)
        else:
            proc = await asyncio.create_subprocess_exec(*self._player, path)
            await proc.wait()
        if path not in self._cache.values():
            os.unlink(path)

    def close(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)
