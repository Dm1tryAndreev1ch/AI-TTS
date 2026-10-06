import asyncio
import json
import logging
from uuid import UUID
from gateway.config import Settings
from gateway.hooks import AudioCounter
from gateway.models import CallSession
from gateway.protocol import DTMF, ERROR, HANGUP, PCM_8K, UUID_PACKET, ProtocolError, encode_packet, read_packet

log = logging.getLogger('gateway')

class AudioSocketServer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.sessions: dict[UUID, CallSession] = {}
        self.connections: set[asyncio.StreamWriter] = set()
        self.tasks: set[asyncio.Task] = set()
        self.hooks = AudioCounter()
        self.server: asyncio.Server | None = None

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
                    raise ProtocolError('First frame must contain UUID')
                call_id = UUID(bytes=payload)
                if call_id in self.sessions:
                    raise ProtocolError('Duplicate call UUID')
                session = CallSession(call_id=call_id)
                self.sessions[call_id] = session
                registered = True
                log.info(json.dumps({'event': 'call_started', 'call_id': str(call_id)}))
                while True:
                    kind, payload = await read_packet(reader)
                    if kind in (HANGUP, ERROR):
                        break
                    if kind == PCM_8K:
                        await self.hooks.on_audio_chunk(session, payload)
                        if self.settings.echo_audio:
                            writer.write(encode_packet(PCM_8K, payload))
                            await writer.drain()
                    elif kind != DTMF:
                        raise ProtocolError('Unsupported packet type')
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError, ProtocolError) as exc:
            log.info(json.dumps({'event': 'connection_closed', 'call_id': str(call_id) if call_id else None, 'reason': type(exc).__name__}))
        finally:
            if registered:
                session = self.sessions.pop(call_id)
                log.info(json.dumps({'event': 'call_finished', 'call_id': str(call_id), 'received_bytes': session.received_bytes}))
            self.connections.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            if task:
                self.tasks.discard(task)
