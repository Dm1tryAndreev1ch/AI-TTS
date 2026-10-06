import asyncio
from gateway.voice.segmenter import FRAME_SAMPLES, SAMPLE_RATE


class MicSource:
    """Microphone frames (512 samples, 16 kHz, mono, int16) delivered to asyncio."""

    def __init__(self, loop: asyncio.AbstractEventLoop, max_frames: int = 500) -> None:
        self._loop = loop
        self._q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=max_frames)
        self._stream = None

    def _put(self, data: bytes | None) -> None:
        if self._q.full():
            self._q.get_nowait()  # drop the oldest frame instead of growing without bound
        self._q.put_nowait(data)

    def _callback(self, indata, frames, time_info, status) -> None:
        self._loop.call_soon_threadsafe(self._put, bytes(indata))

    def start(self) -> None:
        import sounddevice as sd
        self._stream = sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=FRAME_SAMPLES,
                                         channels=1, dtype="int16", callback=self._callback)
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    async def get(self) -> bytes | None:
        return await self._q.get()

    def flush(self) -> None:
        while not self._q.empty():
            self._q.get_nowait()
