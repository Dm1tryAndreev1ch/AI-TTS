import asyncio
import contextlib
from collections.abc import Callable
from typing import Protocol
from uuid import UUID
from gateway.audiosocket import Connection
from gateway.protocol import ProtocolError
from gateway.telephony.resample import resample_to_8k, upsample_8k_to_16k
from gateway.voice.loop import Stt, Vad, run_voice_loop

FRAME_8K_BYTES = 512  # 256 samples at 8 kHz == one 512-sample 32 ms frame at 16 kHz


class PcmTts(Protocol):
    async def synth(self, text: str) -> tuple[bytes, int]: ...


class StartableCall(Protocol):
    finished: bool
    async def start(self) -> None: ...
    async def handle_user_text(self, text: str) -> None: ...
    async def on_silence(self) -> None: ...
    async def hangup(self) -> None: ...


class AudioSocketFrameSource:
    """Turns 8 kHz AudioSocket chunks into 16 kHz 512-sample frames for the voice loop."""

    def __init__(self, max_frames: int = 500) -> None:
        self._q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=max_frames)
        self._buf = bytearray()
        self._closed = False

    def _put(self, item: bytes | None) -> None:
        if self._q.full():
            self._q.get_nowait()
        self._q.put_nowait(item)

    def feed(self, pcm8k: bytes) -> None:
        self._buf += pcm8k
        while len(self._buf) >= FRAME_8K_BYTES:
            chunk = bytes(self._buf[:FRAME_8K_BYTES])
            del self._buf[:FRAME_8K_BYTES]
            self._put(upsample_8k_to_16k(chunk))

    def close(self) -> None:
        self._closed = True
        self._put(None)

    async def get(self) -> bytes | None:
        if self._closed and self._q.empty():
            return None
        return await self._q.get()

    def flush(self) -> None:
        while not self._q.empty():
            self._q.get_nowait()
        self._buf.clear()


class AudioSocketSpeaker:
    def __init__(self, conn: Connection, tts: PcmTts) -> None:
        self._conn, self._tts = conn, tts

    async def say(self, text: str) -> None:
        pcm, rate = await self._tts.synth(text)
        await self._conn.play(resample_to_8k(pcm, rate))


async def serve_call(call_id: UUID, conn: Connection, *, make_call: Callable[[str, AudioSocketSpeaker], StartableCall],
                     vad: Vad, stt: Stt, tts: PcmTts, on_text: Callable[[str], None] | None = None) -> None:
    """Run one phone call: caller audio -> VAD -> STT -> dialog -> TTS -> caller."""
    source = AudioSocketFrameSource()

    async def pump() -> None:
        try:
            async for pcm in conn.audio():
                source.feed(pcm)
        except (asyncio.IncompleteReadError, ConnectionError, ProtocolError):
            pass
        finally:
            source.close()

    pump_task = asyncio.create_task(pump())
    call = make_call(str(call_id), AudioSocketSpeaker(conn, tts))
    vad.reset()
    try:
        await call.start()
        await run_voice_loop(source, vad, stt, call, on_text=on_text)
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
        await conn.hangup()
