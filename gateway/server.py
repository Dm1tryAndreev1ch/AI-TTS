import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID
from gateway.audiosocket import Connection
from gateway.hooks import AudioCounter
from gateway.models import CallSession
from gateway.protocol import HANGUP, UUID_PACKET, ProtocolError, encode_packet, read_packet

log = logging.getLogger("gateway")

CallHandler = Callable[[UUID, Connection], Awaitable[None]]


@dataclass(frozen=True)
class ServerSettings:
    audiosocket_host: str = "127.0.0.1"
    audiosocket_port: int = 9092
    max_calls: int = 1
    call_timeout_sec: int = 600
    echo_audio: bool = False


class AudioSocketServer:
    """Accepts Asterisk AudioSocket connections and runs a handler per call.
    `settings` may be ServerSettings or any object with the same attributes."""

    def __init__(self, settings, handler: CallHandler | None = None, *, pace_s: float = 0.02) -> None:
        self.settings = settings
        self.handler = handler or self._count_handler
        self.pace_s = pace_s
        self.sessions: dict[UUID, CallSession] = {}
        self.connections: set[asyncio.StreamWriter] = set()
        self.tasks: set[asyncio.Task] = set()
        self.hooks = AudioCounter()
        self.server: asyncio.Server | None = None

    @property
    def port(self) -> int:
        assert self.server is not None
        return self.server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self.server = await asyncio.start_server(self.handle, self.settings.audiosocket_host, self.settings.audiosocket_port)

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in tuple(self.connections):
            writer.close()
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _count_handler(self, call_id: UUID, conn: Connection) -> None:
        session = self.sessions[call_id]
        async for pcm in conn.audio():
            await self.hooks.on_audio_chunk(session, pcm)
            if self.settings.echo_audio:
                await conn.send_audio(pcm)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task:
            self.tasks.add(task)
        call_id: UUID | None = None
        registered = False
        try:
            if len(self.connections) >= self.settings.max_calls:
                writer.write(encode_packet(HANGUP))
                await writer.drain()
                return
            self.connections.add(writer)
            async with asyncio.timeout(self.settings.call_timeout_sec):
                kind, payload = await asyncio.wait_for(read_packet(reader), timeout=5)
                if kind != UUID_PACKET:
                    raise ProtocolError("First frame must contain UUID")
                call_id = UUID(bytes=payload)
                if call_id in self.sessions:
                    raise ProtocolError("Duplicate call UUID")
                self.sessions[call_id] = CallSession(call_id=call_id)
                registered = True
                log.info(json.dumps({"event": "call_started", "call_id": str(call_id)}))
                await self.handler(call_id, Connection(reader, writer, pace_s=self.pace_s))
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError, ProtocolError) as exc:
            log.info(json.dumps({"event": "connection_closed", "call_id": str(call_id) if call_id else None,
                                 "reason": type(exc).__name__}))
        except Exception as exc:  # a failing handler must not take the server down
            log.error(json.dumps({"event": "handler_failed", "call_id": str(call_id) if call_id else None,
                                  "reason": type(exc).__name__}))
        finally:
            if registered and call_id is not None:
                session = self.sessions.pop(call_id)
                log.info(json.dumps({"event": "call_finished", "call_id": str(call_id),
                                     "received_bytes": session.received_bytes}))
            self.connections.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            if task:
                self.tasks.discard(task)
