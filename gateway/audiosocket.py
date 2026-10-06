import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from gateway.protocol import DTMF, ERROR, HANGUP, PCM_8K, ProtocolError, encode_packet, read_packet

CHUNK_BYTES = 320  # 20 ms of 8 kHz PCM16
MAX_PAYLOAD = 65534  # even and below the 65535 protocol limit

Sleep = Callable[[float], Awaitable[None]]


class Connection:
    """One AudioSocket connection: caller audio in, agent audio out, hangup."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, pace_s: float = 0.02,
                 sleep: Sleep = asyncio.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        self._reader, self._writer = reader, writer
        self._pace, self._sleep, self._clock = pace_s, sleep, clock
        self.peer_closed = False
        self._hung_up = False

    async def audio(self) -> AsyncIterator[bytes]:
        """Yield caller PCM chunks until the peer hangs up or the connection drops."""
        try:
            while True:
                kind, payload = await read_packet(self._reader)
                if kind in (HANGUP, ERROR):
                    self.peer_closed = True
                    return
                if kind == PCM_8K:
                    yield payload
                elif kind != DTMF:
                    raise ProtocolError("Unsupported packet type")
        except (asyncio.IncompleteReadError, ConnectionError):
            self.peer_closed = True
            raise

    async def _write(self, data: bytes) -> bool:
        try:
            self._writer.write(data)
            await self._writer.drain()
            return True
        except (ConnectionError, OSError):
            self.peer_closed = True
            return False

    async def send_audio(self, pcm: bytes) -> None:
        """Send audio as fast as possible (used for echo)."""
        pcm = pcm[: len(pcm) // 2 * 2]
        for i in range(0, len(pcm), MAX_PAYLOAD):
            if self.peer_closed or self._hung_up or not await self._write(encode_packet(PCM_8K, pcm[i:i + MAX_PAYLOAD])):
                return

    async def play(self, pcm: bytes) -> None:
        """Send audio in 20 ms chunks paced to real time so Asterisk never buffers a whole phrase."""
        pcm = pcm[: len(pcm) // 2 * 2]
        next_t = self._clock()
        for i in range(0, len(pcm), CHUNK_BYTES):
            if self.peer_closed or self._hung_up:
                return
            if not await self._write(encode_packet(PCM_8K, pcm[i:i + CHUNK_BYTES])):
                return
            next_t += self._pace
            delay = next_t - self._clock()
            if delay > 0:
                await self._sleep(delay)

    async def hangup(self) -> None:
        if not self.peer_closed and not self._hung_up:
            self._hung_up = True
            await self._write(encode_packet(HANGUP))
